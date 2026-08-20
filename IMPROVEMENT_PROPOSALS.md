# ahclib 改修提案

調査日: 2026-08-20

## 結論

次に追加するなら、Optuna の best trial を通常テスト結果として保存する機能が最も便利です

現在は Optuna の集約 score と parameter は確認できますが、best trial のケース別 score、出力、入力パラメータを通常の `vis` で詳しく確認できません
最適化終了後の確認作業を短縮でき、既存の詳細結果画面もそのまま再利用できます

次点は実行 manifest と CPU ID の明示指定です
この 2 つを組み合わせると、比較対象が同じ入力と CPU 割り当てで実行されたか確認できます

## 現在の良い点

- 通常テストはケースごとの CPU affinity を任意で有効化できる
- 同じ CPU に複数ケースを同時実行せず、Optuna の複数セッション間でも CPU ごとのロックを共有する
- CLI 未指定時は `AHCSettings.cpu_affinity` を使い、古い settings との互換性も維持している
- [`ResultStore`](ahclib/vis/data.py) は CSV ごとのキャッシュと全結果のキャッシュを持っている
- 詳細結果は Dash AG Grid による sort、filter、列表示切り替えに対応している
- 通常グラフの一部は `WebGL` を使っている
- `vis_beam` は全履歴を `dcc.Store` へ送らず、必要なタブを開いた時だけ表示内容を生成する
- `vis_beam` は turn 別索引と容量制限付き LRU キャッシュを使い、アプリごとに履歴とキャッシュを分離している
- Optuna の停止処理、孤立 trial の回収、Tailscale Serve の終了処理まで考慮されている

## 優先順位

| 優先度 | 提案 | 主な効果 | 規模 |
|---|---|---|---|
| P1 | Optuna の best trial を通常結果として保存 | ケース別分析、`vis` の再利用 | 中 |
| P1 | 実行 manifest の保存 | 再現性、比較条件の確認 | 中 |
| P1 | 使用する CPU ID の明示指定 | CPU 条件の安定化 | 小 |
| P2 | run の tag と比較基準の管理 | 日常操作の短縮 | 中 |
| P2 | Optuna パラメータの再利用コマンド | 手作業と転記ミスの削減 | 小 |
| P2 | `doctor` コマンド | 導入と障害調査 | 中 |
| P2 | 保存結果の安全な一覧表示と整理 | 容量管理 | 中 |
| P2 | Beam node の比較と検索強化 | 調査効率 | 中 |
| P3 | Tailscale 経由の読み取り専用 `vis_beam` | 外部端末からの確認 | 中 |

## 追加すると便利な機能

### F1 Optuna の best trial を通常結果として保存する

目的

- best trial のケース別 score、time、state、出力を通常の `vis` で確認する
- Base run と比較し、どの入力パラメータで改善または悪化したか調べる

提案

- `python -m ahclib opt --record-best` を追加する
- 最適化終了後、完了済みの best trial を `ParallelTester.run_record()` で 1 回実行する
- trial の `ahclib_execute_args` を使い、parameter から実行引数を作り直さない
- 通常どおり `ahclib_results/all_tests/<run_id>/` へ保存する
- memo と tag に study name、trial number、目的値を記録する
- `study.json` に保存した通常 run の ID を記録する
- CPU affinity、入力一覧、集計方法は最適化時と同じものを使う
- best trial がない場合や実行引数が保存されていない古い study では明示的に中止する

既定で再実行すると終了時間が延びるため、最初はオプション指定時だけ実行するのが安全です

### F2 実行 manifest

各 run に `manifest.json` を追加し、次を保存します

- schema version、run ID、開始日時、終了日時
- hostname、OS、Python、ahclib version
- `compile_command`、`execute_command`、追加した solver 引数
- timeout、`njobs`、CPU affinity、使用 CPU ID、ケースと CPU の対応
- source と settings の hash
- Git commit、branch、dirty の有無、必要なら diff
- 入力一覧とハッシュまたはサイズ、更新日時
- 集計方法、direction、score type、seed
- 親 run、memo、tag、Optuna study と trial number

用途

- Base と Target の入力や集計条件が一致しているか `vis` で警告できる
- CPU 数や `njobs` が違う run の time 比較を避けられる
- best trial の再実行条件を後から確認できる
- 将来の run 再現コマンドと安全な結果整理の基礎になる

既存の source、settings、`result.csv` は残し、追加ファイルだけで実現します

### F3 使用する CPU ID の明示指定

現在の自動選択に加えて、settings へ次を追加します

```python
cpu_ids: list[int] | None = None
```

仕様案

- `None` なら現在どおり利用可能な logical CPU から自動選択する
- リスト指定時はその順番をケース割り当てに使う
- `--cpu-ids 2,4,6` と `--cpu-ids auto` で端末ごとに一時上書きできるようにする
- `sched_getaffinity` の範囲外、重複、空 list は実行前にエラーにする
- 実際に使用する CPU とケースの対応をログと manifest に保存する
- WSL では物理 core まで保証できないことを表示する

P-core、E-core、SMT の自動判定は環境差が大きいため、最初は明示指定を優先します

### F4 run の tag と比較基準を CLI から管理する

提案する操作

```text
ahclib test --tag candidate-a
ahclib test --base latest
ahclib test --base tag:stable
ahclib baseline set <run_id>
ahclib baseline show
```

仕様案

- `--tag` は実行時に `.ahclib_vis.json` へ保存する
- `--base` は `pre_dir_name` を一時的に上書きする
- `latest` は入力、direction、score type が互換な最新 run だけを対象にする
- tag が複数 run に付いている場合は最新を使い、選択した run ID をログへ表示する
- manifest がない古い run は自動選択せず、run ID の明示指定だけ許可する

毎回 `pre_dir_name` を編集する作業を減らし、誤った Base との比較も防げます

### F5 Optuna parameter を通常テストで再利用する

提案する操作

```text
ahclib opt best --study <study_name>
ahclib test --trial <study_name>:best
ahclib test --trial <study_name>:123
```

提案

- `opt best` は value、parameter、実際の solver 引数を簡潔に表示する
- `test --trial` は trial の `ahclib_execute_args` を通常テストへ渡す
- `best_args.txt` または `best_args.json` も出力する
- source や settings の hash が異なる場合は警告する
- settings file を自動編集する機能は追加しない

自動編集を避けることで、便利さを保ちながら contest code の意図しない変更を防げます

### F6 `ahclib doctor`

実行前に次をまとめて確認します

- settings の読み込みと必須属性
- コンパイラと solver コマンドの存在
- 入力ファイル数、重複 basename、読み込み権限
- 結果ディレクトリの書き込み権限と空き容量
- score 出力形式の簡易確認
- `cpu_affinity`、`cpu_ids`、`taskset`、利用可能 CPU
- Optuna storage の読み込み
- `--tailscale` 指定時の daemon、login、Serve 権限
- Dashboard の port 使用状況

確認だけを行い、package install、権限変更、Tailscale 設定変更は自動実行しません

### F7 保存結果を安全に整理する

提案する操作

```text
ahclib runs
ahclib runs --size
ahclib clean --older-than 14d --dry-run
ahclib clean --older-than 14d
```

安全方針

- `runs` は run ID、日時、tag、memo、サイズ、study との関連を一覧表示する
- `clean` は既定で削除候補だけを表示する
- tag 付き run、baseline、Optuna best に関連する run は保護する
- 実際の削除前に対象の絶対パスと合計サイズを表示して確認する
- `clear` コマンドは全削除用途として残し、役割を分ける

### F8 Beam node の調査操作を強化する

- 2 つの node を選び、score、state、action path を比較する
- 検索結果を一覧表示し、前後の一致 node へ移動する
- 親、子、次の active node へ keyboard で移動する
- bookmark へ名前と memo を付け、JSON へ保存する
- score 範囲、status、hash 重複で絞り込む
- node 数が多い時は簡略表示し、選択部分だけ展開する

path や subtree の export より、画面上の比較と移動を優先します

### F9 Tailscale 経由の読み取り専用 `vis_beam`

- 通常の `vis` と同じ Tailscale Serve を使う
- 外部共有時は読み取り専用にする
- Funnel は使わず、tailnet 内限定を維持する
- 起動時に local URL、private URL、access scope、read-only を表示する
- bookmark や memo の保存 callback も server 側で無効にする

## 並列テストと Optuna の効率改善

### T1 stderr の出力量に上限がない

根拠

- stderr は score 抽出とエラー確認のために全体をメモリへ取り込む
- solver が大量に出力した場合はメモリ使用量が増える

提案

- stderr は score 抽出に必要な末尾だけを容量制限付きで保持する
- 出力量超過を `OLE` などの明示状態にする

### T2 Optuna の各 trial で入力ファイルを読み直す

提案

- 小さい入力群は tester 作成時に読み込み、全 trial から再利用する
- 大きい入力群は現在どおり OS のファイルキャッシュに任せる
- 合計入力サイズを見て自動選択し、メモリ上限を設定できるようにする

### T3 打ち切り確認が各 solver で 50 ms ごとの polling になっている

提案

- polling 間隔を settings で変更できるようにする
- `njobs` が大きい場合は、共通監視側で process 終了を管理する方式も比較する
- 既定値は停止反応が悪化しない範囲で維持する

### O1 Optuna 終了時に全グラフを毎回再生成する

提案

- `html`、`png`、`none` を設定可能にする
- PNG は明示指定時だけ生成する
- 前回出力時の trial 数と同じなら再生成しない
- 終了処理の各工程に所要時間を表示する

## 今回は追加しない機能

過去の方針に合わせ、次は提案対象から外します

- テスト途中結果の保存
- 失敗ケースだけの再実行
- 詳細結果の全文ダウンロード
- グラフの Zoom reset button

## 安全性と互換性の方針

- 現在の `result.csv`、`study.json`、`history.json` は読み続けられるようにする
- 新しい列や JSON file は追加形式とし、過去結果の一括変換を必須にしない
- 削除コマンドは dry-run と対象パスの確認を既定にする
- settings に新しい項目がない場合は現在の既定値を使う
- 外部共有時は読み取り専用を既定にする
- Tailscale Funnel や `0.0.0.0` への直接公開は既定機能にしない
- custom `visualizer.html` と `visualizer.py` は信頼済みローカルコードとして扱う

## 推奨する実装順

### 第 1 段階 Optuna の確認作業を短縮する

1. best trial の solver 引数を表示する
2. `--record-best` で通常結果を保存する
3. 保存した run を `study.json` から参照できるようにする

### 第 2 段階 比較条件を明確にする

1. manifest
2. CPU ID の明示指定
3. Base と Target の互換性警告

### 第 3 段階 日常操作を短縮する

1. tag と baseline 管理
2. `doctor`
3. 保存結果の一覧表示と安全な整理

### 第 4 段階 Beam の調査機能を強化する

1. node 比較と検索結果一覧
2. bookmark の永続化
3. 読み取り専用の外部共有

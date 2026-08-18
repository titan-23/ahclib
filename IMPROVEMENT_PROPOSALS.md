# ahclib 改修提案

調査日: 2026-08-18

## 結論

現在残っている案では、再現用 manifest が特に実用的です

## 現在の良い点

- [`ResultStore`](ahclib/vis/data.py) は CSV ごとのキャッシュと全結果のキャッシュを既に持っている
- 通常グラフの一部は `WebGL` を使っている
- `vis_beam` は全履歴を `dcc.Store` へ送らず、更新通知だけをブラウザーへ送っている
- `vis_beam` は統計タブや全体グラフを開いた時だけ生成している
- `vis_beam` は turn 別索引と容量制限付き LRU を使い、app ごとに履歴と cache を分離している
- 並列テストは外部ソルバーの待機が中心なので、現在の `ThreadPoolExecutor` は用途に合っている
- Optuna の停止処理、孤立 trial の回収、Tailscale Serve の終了処理まで考慮されている

## 優先順位

| 優先度 | 提案 | 主な効果 | 規模 |
|---|---|---|---|
| P1 | 実行 manifest の保存 | 再現性、比較の確実性 | 中 |
| P2 | Beam ノード比較、検索結果一覧、永続ブックマーク | 調査効率 | 中 |
| P2 | `doctor` コマンド | 導入と障害調査 | 中 |

## 並列テストと Optuna の改善案

### T1 記録しない実行でも stdout 全体をメモリへ取り込む

根拠

- ソルバー実行は常に stdout と stderr を `capture_output` する
- Optuna と `--no-record` では、score 抽出後の stdout は通常使わない

提案

- 記録しない場合は stdout を破棄できる設定を追加する
- stderr は score 抽出に必要な末尾だけを容量制限付きで保持する選択肢を用意する
- 出力量超過を `OLE` などの明示状態にする

### T2 Optuna の各 trial で入力ファイルを読み直す

提案

- 小さい入力群は tester 作成時に読み込み、全 trial から再利用する
- 大きい入力群は現在どおり OS の file cache に任せる
- 合計入力サイズを見て自動選択し、メモリ上限を設定できるようにする

### T3 打ち切り確認が各 solver で 50 ms ごとの polling になっている

提案

- pruner 使用時の CPU 使用率を計測する
- 反応時間を保てる範囲で polling 間隔を設定可能にする
- `njobs` が大きい場合は、共通監視側で process 終了を管理する方式も比較する

これは solver 自体の負荷に隠れる可能性があるため、計測後に着手を判断します

### O1 Optuna 終了時に全グラフを毎回再生成する

根拠

- [`_output_plots()`](ahclib/optimizer.py#L753-L771) は 6 種類の HTML と PNG を毎回生成する
- trial 数が多い study では終了処理が長くなる可能性がある

提案

- `html`、`png`、`none` を設定可能にする
- PNG は明示指定時だけ生成する
- 前回出力時の trial 数と同じなら再生成しない
- 終了処理の各工程に所要時間を表示する

## 追加すると便利な機能

### F1 再現用 manifest

各 run に次を保存します

- run ID、開始日時、終了日時、ホスト名、OS、Python、ahclib version
- コンパイル command、実行 command、timeout、`njobs`
- source と settings の hash
- Git commit、branch、dirty の有無、必要なら diff
- 入力一覧と hash またはサイズ、更新日時
- 集計方法、direction、seed
- 親 run、memo、任意の tag

既存の source と settings のコピーは残し、`manifest.json` を追加する形なら互換性を保てます

### F2 Beam の調査操作を強化する

- 2 node を選んで score、state、action path を比較する
- 検索結果を一覧にし、前後の一致 node へ移動する
- 親、子、次の active node へ keyboard で移動する
- ブックマークへ名前と memo を付け、JSON へ保存する
- path と subtree の export
- score 範囲、status、hash 重複による絞り込み
- ノード数が多い時の簡略表示と、選択部分だけの展開

### F3 Tailscale 経由の読み取り専用 `vis_beam`

- Optuna Dashboard と同じ Tailscale Serve を再利用する
- remote mode は既定で読み取り専用にする
- Funnel は使わず、tailnet 内限定を維持する
- 起動時に local URL、private URL、access scope、read-only を明示する

通常の `vis` と同じ共有方式へそろえます

### F4 `ahclib doctor`

次を実行前にまとめて確認します

- settings の読込と必須属性
- compiler と solver command の存在
- 入力ファイル数、重複 basename、読込権限
- 結果ディレクトリの書込権限と空き容量
- score 出力形式の簡易確認
- Optuna storage の読込
- `--tailscale` 指定時の daemon、login、Serve 権限
- Dashboard の port 使用状況

## 安全性と互換性の方針

- 現在の `result.csv` と `history.json` は読み続けられるようにする
- 新しい列や `manifest.json` は追加形式とし、過去結果の一括変換を必須にしない
- `vis_beam` の remote mode は読み取り専用を既定にする
- Tailscale Funnel や `0.0.0.0` への直接公開は既定機能にしない
- custom `visualizer.html` と `visualizer.py` は信頼済みローカルコードとして扱い、その前提を文書化する

## 実装前に行う計測

最適化の効果を判断できるよう、次の fixture を用意します

### 並列テスト

- `njobs` 1、CPU 数、CPU 数を超える値
- stdout なし、少量、大量
- pruner ありとなし
- 計測値は wall time、親 process の CPU、RSS、停止通知から solver 終了までの時間

## 推奨する実装順

### 第 1 段階 再現性を改善する

- manifest

### 第 2 段階 導入と保守を改善する

- `ahclib doctor`

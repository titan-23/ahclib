# ahclib 改修提案

調査日: 2026-08-18

## 結論

現在もっとも効果が高いのは `vis_beam` の全ノード走査とキャッシュ容量の見直しです
大きな探索履歴では、表示区間が狭くても全ノードを調べ、条件ごとの大きな描画要素を複数保持するため、ノード数に応じて CPU とメモリの両方が増えます

新機能では、再現用 manifest が特に実用的です

## 現在の良い点

- [`ResultStore`](ahclib/vis/data.py) は CSV ごとのキャッシュと全結果のキャッシュを既に持っている
- 通常グラフの一部は `WebGL` を使っている
- `vis_beam` は全履歴を `dcc.Store` へ送らず、更新通知だけをブラウザーへ送っている
- `vis_beam` は統計タブや全体グラフを開いた時だけ生成している
- ビーム探索の木配置、active path、描画要素には既にキャッシュがある
- 並列テストは外部ソルバーの待機が中心なので、現在の `ThreadPoolExecutor` は用途に合っている
- Optuna の停止処理、孤立 trial の回収、Tailscale Serve の終了処理まで考慮されている

このため、全面的な作り直しより、データ更新の境界とキャッシュ単位を整理する方が安全で効果も高いと考えます

## 優先順位

| 優先度 | 提案 | 主な効果 | 規模 |
|---|---|---|---|
| P1 | `vis_beam` のターン別索引と容量制限付き LRU | 大規模履歴の速度とメモリ | 中から大 |
| P1 | 実行 manifest の保存 | 再現性、比較の確実性 | 中 |
| P2 | Beam ノード比較、検索結果一覧、永続ブックマーク | 調査効率 | 中 |
| P2 | `doctor` コマンドと依存関係の分割 | 導入と障害調査 | 中 |

## `vis_beam` 周辺の非効率と改善案

### B1 表示区間が狭くても全ノードを走査する

根拠

- [`update_elements()`](ahclib/beam/app.py#L763-L794) は表示区間を選んだ後も全ノードを走査する
- [全体スコア推移](ahclib/beam/app.py#L1047-L1102) もスライダー更新ごとに全ノードを走査する
- `load_and_process_data()` が作る `nodes_sorted` は現在使われていない

提案

- 読み込み時に `nodes_by_turn` と辺のターン別索引を作る
- 表示区間に含まれる部分だけを `bisect` または辞書参照で取得する
- 親を補う処理はノードごとの祖先再走査ではなく、必要 ID の集合を一度作って処理する
- 全体グラフ用の座標列もターン別に事前作成する

期待効果

- 更新時間を全ノード数ではなく、主に表示ノード数へ比例させられる

### B2 描画要素キャッシュがメモリ量ではなく件数だけで制限される

根拠

- [`elements_cache`](ahclib/beam/app.py#L643-L655) は条件ごとの node と edge 全体を保持する
- 64 件に達すると全消去するが、1 件が大きい場合の上限はない
- `_BOARD_CACHE` は件数上限を持たない
- compact layout と active path のキャッシュも履歴中のターン数に応じて増える

提案

- `OrderedDict` などを使った LRU にし、件数と概算要素数の両方で制限する
- `elements` 全体ではなく、変化しない node 基本情報と状態差分を分ける
- board は選択回数の多い直近だけを保持する
- キャッシュ hit、miss、要素数、概算容量を debug 表示できるようにする

期待効果

- 大きな履歴でもメモリ上限を予測しやすくなり、全消去直後の再計算も減らせる

### B3 ノード選択時に子孫全体を毎回たどる

根拠

- [ノード詳細表示](ahclib/beam/app.py#L1294-L1428) は選択ノードの子孫を全て走査し、長い Cytoscape selector 文字列を作る
- 根に近いノードでは履歴全体に近い量になる

提案

- 現在表示されている node と edge だけを強調対象にする
- 同じノードの子孫結果は小さな LRU へ保持する
- 子孫全体の強調と、直下の枝だけの強調を分ける
- 大規模履歴では既定を path と直下の子だけにする

### B4 module global の状態がアプリ単位に分離されていない

根拠

- `_DATA_CACHE`、`_HISTORY_PATH`、`_generate_board_visual`、`_BOARD_CACHE` が module global になっている
- 1 process で複数アプリを作るテストや、将来複数ユーザーを扱う時に状態が混ざる

提案

- `BeamStore` を作り、`create_app()` ごとの closure で保持する
- 読み込んだ履歴は不変スナップショットとして一度に差し替える
- ブックマークや折り畳みはブラウザー session 側、履歴解析結果はサーバー側と役割を分ける

### B5 読み込み時に不要な値も保持している

確認候補

- `turn_stats` は全 score 配列を保持し、別に全 node も保持する
- `valid_scores`、`nodes_sorted`、描画用追加キーも同じ履歴から作られる
- `marks` を計算しているがコールバックは `None` を返している

提案

- 実測した上で、統計図に必要な値だけを保持する集計モードを用意する
- 詳細表示用 node と統計用配列の重複量を計測する
- `marks` を表示へ使うか、計算自体を削除する
- 10 万 node を超える場合は、全体表示を簡略化する Level of Detail モードを検討する

この項目は履歴の典型的な大きさによって効果が変わるため、先に計測します

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

### `vis_beam`

- node 数 1 万、10 万、可能なら 100 万
- 全区間と狭い区間
- pruned 表示、compact、heatmap、検索、折り畳み
- 根、葉、中間 node の選択
- 計測値は履歴読込時間、tree layout 時間、callback 時間、elements 数、返却 JSON サイズ、RSS

### 並列テスト

- `njobs` 1、CPU 数、CPU 数を超える値
- stdout なし、少量、大量
- pruner ありとなし
- 計測値は wall time、親 process の CPU、RSS、停止通知から solver 終了までの時間

## 推奨する実装順

### 第 1 段階 計測環境を整える

- `vis_beam` の小、中、大履歴 fixture
- 上記の基準計測を追加

### 第 2 段階 `vis_beam` を大規模履歴へ対応させる

- module global の解消
- ターン別索引
- 容量制限付き LRU
- 表示 node だけの subtree 強調
- Level of Detail の必要性を再計測

### 第 3 段階 再現性を改善する

- manifest

### 第 4 段階 導入と保守を改善する

- `ahclib doctor`

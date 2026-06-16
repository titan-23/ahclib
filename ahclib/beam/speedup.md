# ビームサーチ可視化ツールの高速化案

`python3 -m ahclib vis_beam` で起動する `ahclib/beam/` を対象とする。行番号は次のファイル基準。

- `ahclib/beam/app.py`: `create_app` と全コールバック
- `ahclib/beam/data.py`: `load_and_process_data` と `compute_tree_layout`
- `ahclib/beam/config.py`: テーマと `BASE_STYLESHEET`
- `ahclib/main.py`: 起動部

## 前提

- Dash と dash_cytoscape を維持する。
- 木の形を今と同一に保つ。`compute_tree_layout`、`base_positions`、全ノード描画を維持する。場所は data.py:6-136 と data.py:327-338。
- 形は描画器に依存しない。座標は Python 側で確定し、Cytoscape は `preset` で描くだけ。app.py:577-583 と app.py:795-801。交差しないのは配置計算側の性質。

## 重さの構造

- ブラウザ描画。dash_cytoscape が支配的。要素が数千を超えると描画が遅くなる。
- サーバ計算。`update_elements` が多入力で頻発し、毎回 elements 全体を作り直す。
- 転送。作り直した elements を毎回ブラウザへ再送する。

## 改善余地は2種類

- A 操作の無駄。操作のたびに繰り返す再計算、再送、スタイルの再適用。木の形に無関係。取り戻せる。
- B 定常描画の下限。N 個のノードと辺を Cytoscape が描く時間。形固定では N は減らせない。定数倍だけ改善できる。下限を動かせるのは WebGL 描画だけ。

## 既に対応済み

- `debug=False` で起動する。main.py:110。
- ノードを読込時に整列し `nodes_sorted` として持つ。data.py:340 と data.py:350。`update_elements` は毎回整列しない。app.py:649。
- 盤面生成を `_BOARD_CACHE` でキャッシュする。app.py:1154-1156。
- 共通祖先の計算の重複ループを1本に統合する。data.py:266-303。
- 全体スコア推移は WebGL で描く `Scattergl` を使う。app.py:960-968。
- 辺はヒット判定を切ってある。config.py:87。

## 概要表

| # | 案 | 分類 | 効果 | 手間 |
|---|---|---|---|---|
| 1.1 | クリック時のスタイルシート全置換を廃止 | A | 大 | 中 |
| 1.2 | 検索・ヒートマップ・破棄表示をクラス切替へ | A | 中 | 中 |
| 1.3 | 再生と走査を1回描画と切替へ | A | 大 | 中 |
| 1.4 | 生存経路を事前計算 | A | 中 | 中 |
| 1.5 | 折畳が空なら折畳判定をスキップ | A | 中 | 小 |
| 1.6 | elements の結果を保持して再利用 | A | 中 | 小 |
| 2.1 | スライダを `updatemode="mouseup"` に | A | 中 | 小 |
| 2.2 | 全体スコア推移を表示中のタブだけで計算 | A | 中 | 小 |
| 2.3 | 盤面とスコア図を遅延計算 | A | 中 | 小 |
| 2.4 | コールバックを役割で分割 | A | 中 | 中 |
| 3.1 | 辺を `bezier` から `straight` へ | B | 中 | 小 |
| 3.2 | `min-zoomed-font-size` と範囲外の `display:none` | B | 中 | 小 |
| 3.3 | 文字なしノードの label を送らない | B | 中 | 小 |
| 3.4 | ラベルを単一行にし `text-wrap` を解除 | B | 小 | 小 |
| 3.5 | ヒートマップ色を読込時に1回計算 | A | 中 | 小 |
| 3.6 | Cytoscape の初期化設定 | B | 中 | 小〜中 |
| 4.1 | Cytoscape の WebGL 描画 | B | 大 | 中 |
| 5.1 | `flask-compress` で gzip 圧縮 | 転送 | 中 | 小 |
| 5.2 | ファイル無変更なら再処理をスキップ | 読込 | 中 | 小 |
| 5.3 | 共通祖先の計算を軽くする | 読込 | 中 | 中 |
| 5.4 | 頻繁に回るループの `str()` を減らす | A | 小 | 小 |
| 5.5 | 要素の雛形を事前生成 | A | 中 | 中 |

## 1. 操作の無駄を消す

最優先の区分。

### 1.1 クリック時のスタイルシート全置換を廃止

`display_node` が毎クリックでスタイルシート全体を作り直す。app.py:1000-1337。部分木と経路のノードIDをすべて列挙したカンマ区切りセレクタに展開し、全要素に再マッチする。場所は app.py:1227-1335。出力先は `Output("cytoscape-tree", "stylesheet")`。app.py:1006。根に近いノードでは要素数 N に対し O(N^2) 級になる。強調表示は木の形に無関係。対応はクラス方式に変える。`.hl-path`、`.hl-subtree`、`.hl-goal` を `BASE_STYLESHEET` に静的に定義し、クライアント側コールバックで Cytoscape にクラスを付け外しする。サーバとの往復もスタイルシートの再解析も消える。コストは触ったノード数に比例する。クリック体感の主因はここ。

### 1.2 検索・ヒートマップ・破棄表示をクラス切替へ

検索、ヒートマップ、破棄表示はいずれも `update_elements` の全再構築を誘発する。場所は app.py:736-741、app.py:763-765、app.py:656 と app.py:703。描画済み要素のクラス切替に変える。

### 1.3 再生と走査を1回描画と切替へ

`update_elements` は9入力で発火し、毎回 elements を作り直して再送する。app.py:541-803。再生と走査では毎フレーム走る。`dcc.Interval` は app.py:54、`handle_play` は app.py:519-539。範囲内を1回描き、現在ターンは表示と強調の切替だけで表す。

### 1.4 生存経路を事前計算

今は発火の度に根まで遡る。app.py:603-623。`valid_max_t` ごとに読込時に計算して保持し、再生と走査の各フレームから外す。

### 1.5 折畳が空なら折畳判定をスキップ

`is_ancestor_collapsed` は `nodes_sorted` 上を毎回全件走査する。app.py:647-654。整列は読込時に済むが、走査自体は毎回走る。折畳が空ならスキップする。空でないときも、折り畳んだノードからの幅優先探索で隠す集合だけ求める。計算量は折り畳んだ部分木の大きさに収まる。

### 1.6 elements の結果を保持して再利用

`turn_range`、`visibility`、`direction`、`collapsed`、`bookmark`、`search` の組をキーに結果を保持し、走査の往復を即時化する。

## 2. 発火を減らす

### 2.1 スライダを `updatemode="mouseup"` に

操作中の連続発火を、離した時の1回に減らす。app.py:73-81。一行で済む。

### 2.2 全体スコア推移を表示中のタブだけで計算

`update_all_graph` は `turn-range-slider` を入力に持ち、走査の度に `Scattergl` を作り直す。app.py:929-977。`left-tabs` の値で表示中のときだけ計算する。`update_turn_stats` は `full-data-store` だけが入力で読込時に1回なので、優先度は低い。app.py:805-927。

### 2.3 盤面とスコア図を遅延計算

`display_node` は1クリックで詳細、盤面、スコア図、スタイルシートを全部出す。app.py:1000-1337。盤面とスコア図を `info-tabs` の値で表示中のときだけ計算する。

### 2.4 コールバックを役割で分割

`display_node` の出力にスタイルシートが含まれる。app.py:1000-1006。側パネルだけ要るクリックでもグラフ全体でスタイルが再適用される。構造、装飾、側パネルを別コールバックに分け、装飾の変更でグラフ全体を触らない構成にする。1.1 と合わせて行う。

## 3. 描画コストを下げる

形は変えない。効果は定数倍。

### 3.1 辺を `bezier` から `straight` へ

`curve-style: bezier` を `straight` にする。config.py:82。描画と視点移動・拡大縮小の再計算が軽くなる。木なので交差は出ない。

### 3.2 `min-zoomed-font-size` と範囲外の `display:none`

縮小時にラベル描画を止め、範囲外ノードは `display: none` で描画から外す。範囲外は `out-of-range` クラスが付く。app.py:743-744。

### 3.3 文字なしノードの label を送らない

status-pruned と status-invalid は font-size 0 で文字を出さない。config.py:38 と config.py:47。それでも要素に label を必ず付けている。app.py:747。これらの `data.label` を省き、転送量とテキスト処理を削る。見た目は変わらない。

### 3.4 ラベルを単一行にし `text-wrap` を解除

`text-wrap: wrap` の2行ラベルの折返し計算が N 件分かかる。config.py:27。単一行にして削る。見た目が少し変わるので要確認。

### 3.5 ヒートマップ色を読込時に1回計算

今は切替の度に全ノードで `get_heatmap_color` を回す。app.py:659-668 と app.py:763-764。色をノードに持たせ、表示切替はクラスで行えば再計算が消える。

### 3.6 Cytoscape の初期化設定

`textureOnViewport: true`、`hideEdgesOnViewport: true`、`pixelRatio: 1`、`motionBlur: false`、`boxSelectionEnabled: false` を設定する。視点移動中はキャッシュ画像を描き、辺を一時的に隠す。`cyto.Cytoscape` のプロパティとして渡す。app.py:268-290。dash_cytoscape が通すか要検証。通らなければコンポーネントへの修正が要る。

## 4. 描画の下限を上げる

下限を動かせる唯一の手。

### 4.1 Cytoscape の WebGL 描画

`renderer: {name:"canvas", webgl:true}` 相当を `cyto.Cytoscape` に渡す。app.py:268。座標、API、スタイルを据え置いたまま N の上限が上がる。全ノード描画を保ったまま数万規模に耐える。dash_cytoscape が renderer 指定を通すか要検証。通らなければコンポーネントへの修正が要る。

## 5. 読込と転送

### 5.1 `flask-compress` で gzip 圧縮

elements の JSON は反復構造で圧縮が効く。`create_app` 内で `Compress(app.server)` を呼ぶ。app.py:33-38。転送量が落ちる。

### 5.2 ファイル無変更なら再処理をスキップ

`load_data` は再読み込みボタンと `keyboard-manager` の変更で都度全処理する。app.py:505-517。`_HISTORY_PATH` の更新時刻を見て、変化がなければ `compute_tree_layout` ごと再処理を飛ばす。

### 5.3 共通祖先の計算を軽くする

`data.py:266-303` は各ターンで生存ノードごとに根まで遡り、概ね O(T^2 W) になる。ターン数が大きく再読み込みが重いなら、最小共通祖先を使う方式へ変える。読込時のみの話で、操作の体感とは別軸。

### 5.4 頻繁に回るループの `str()` を減らす

`update_elements` の各所でノードIDを毎回 `str()` で文字列化している。app.py:698-770。読込時に文字列IDを確定させ、ループ内の変換を消す。

### 5.5 要素の雛形を事前生成

id、label、縦横両方向の座標を読込時に作り、発火時はクラスだけ差し替える。不変部分を発火経路から外す。1.3 と 1.6 と合わせて効く。

## 下限について

全ノードを描画し N が数万規模のとき、ノードと辺を Cytoscape が描く時間が下限になる。形固定では N は減らせない。この下限を動かせるのは 4.1 の WebGL 描画だけ。それ以外は N に関係なく取り戻せる無駄か、定数倍の改善で、下限そのものは超えない。

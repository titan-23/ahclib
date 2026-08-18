AHC Lib
===========

`titan23 <https://atcoder.jp/users/titan23?contestType=heuristic>`_  が使用している、AHC のツールです。
ありえないバグがあるかもしれません。ご注意ください。

`View on GitHub <https://github.com/titan-23/ahclib/tree/main>`_


インストール
-------------

repository を clone したディレクトリで、使う機能に合わせてインストールします

.. code-block:: shell

    # setup と clear のみ
    python3 -m pip install .

    # 並列実行と通常の結果表示
    python3 -m pip install ".[test,vis]"

    # Optuna と AutoSampler
    python3 -m pip install ".[opt,auto-sampler]"

    # 全機能を開発用にインストール
    python3 -m pip install -r requirements.txt

``opt`` の旧 PostgreSQL storage を自動移行する場合だけ ``postgres`` も追加します


使い方
-------

初期設定
~~~~~~~~~~~~~~~~~~

作業ディレクトリで以下のコマンドを実行し、設定ファイル ``ahc_settings.py`` を生成します

.. code-block:: shell

    python3 -m ahclib setup



並列実行
~~~~~~~~~~~~~~~~~~

``njobs`` 数のスレッドを立ち上げて実行します。結果を記録した csv ファイルと実行ソースファイルが ``./ahclib_results/all_tests/YYYY_MM_DD_HH_MM_SS/`` に保存され、実行後に保存先が表示されます

コマンドは以下です

.. code-block:: shell

    python3 -m ahclib test [--no-compile] [--no-verbose] [--no-record] [-m MEMO]

**オプション**

コンパイル、ログ表示、入出力の保存はいずれも既定で有効になっている。無効にするときに以下を指定する

- ``--no-compile`` : コンパイルを行わない
- ``--no-verbose`` : per-case のログを表示しない
- ``--no-record`` : 標準出力と標準エラー出力を保存しない
- ``-m``, ``--memo`` : 実行結果に添えるメモを指定する。結果ディレクトリの ``memo.txt`` に保存され ``vis`` で表示される
- ``-s``, ``--settings`` : 設定ファイルのパスを指定する (既定は ``ahc_settings.py``)


実行結果の可視化
~~~~~~~~~~~~~~~~~~

保存済みのテスト結果を表示する場合は、テストを実行したディレクトリで次を実行します

.. code-block:: shell

    python3 -m ahclib vis

実行一覧と詳細結果には Dash AG Grid を使用しています

- 列名をクリックすると並べ替えられる
- ``Ctrl`` を押しながら列名をクリックすると複数列で並べ替えられる
- 詳細結果の列名直下にある入力欄でケースを絞り込める
- ``フィルター解除`` ですべての列フィルターを解除できる
- 並べ替えや絞り込みの後もケース ID を使って選択中の行を識別する
- ``前へ`` と ``次へ``、または ``k`` と ``j`` で現在の表示順に沿ってケースを移動できる
- 改善、悪化、同点、比較不能、失敗、Bookmark でケースを絞り込める
- Target と Base の State、score、rank、time とそれぞれの差分を表示する
- Score、Rank、Time、Best、入力パラメータの列グループを表示切り替えできる
- ``Zoom reset`` でグラフの表示範囲を戻せる
- グラフ種別、列表示、列 filter と並べ替えは browser session に保存される
- Base は手動選択、``直前を Base``、Target の直前へ自動追従から選べる

実行一覧には次の集計値を表示します

- ``Total`` は現在の ``AHCSettings.get_score`` で計算した総合値
- ``Ave`` は算術平均
- ``Median`` は中央値
- ``IQR`` は四分位範囲
- ``CI95 ±`` は算術平均の 95% 信頼区間の半幅 (正規近似)
- ``RelGeo`` は Base に対する正の相対値の幾何平均
- ``Rel N/A`` は Base が 0、欠損などで相対値を計算できないケース数

過去 run の ``Total`` も現在の ``ahc_settings.py`` で計算します
当時の集計方法を保存する機能は今後の manifest 対応で追加する予定です

``AHCSettings.parse_input_params`` が辞書を返す場合は、そのキーを詳細結果の列として追加します
数値は数値フィルター、文字列は文字列フィルターとして扱います

.. code-block:: python

    @staticmethod
    def parse_input_params(file_path: str) -> dict[str, int]:
        with open(file_path, encoding="utf-8") as input_file:
            n, m = map(int, input_file.readline().split())
        return {"N": n, "M": m}

この例では詳細結果へ ``N`` と ``M`` の列が追加されます

実行一覧の Tag と Favorite、ケースごとの Memo と Bookmark は結果 run 内の
``.ahclib_vis.json`` へ保存します
既存の ``result.csv``、入力、出力は変更しません

詳細タブでは Target と Base の err / out を横並びで比較できます
入力、出力、source、diff が大きい場合は先頭と末尾だけを表示し、必要な場合だけ
``全文表示`` を選びます
表示内容の検索と行折り返しも利用できます

``visualizer.html`` はビジュアライザタブを開いた時だけ読み込みます
iframe には ``sandbox`` と Content Security Policy を設定しており、外部通信は許可しません
``visualizer.html`` 自体は信頼できるローカルファイルだけを使用してください

通常の ``vis`` をスマホなどへ共有する場合は次を実行します

.. code-block:: shell

    python3 -m ahclib vis --tailscale

``--tailscale`` では ``127.0.0.1:8050`` を Tailscale Serve へ接続し、tailnet 内だけに共有します
Funnel と ``0.0.0.0`` は使用しません
共有中の画面は読み取り専用になり、削除、Memo、Tag、Favorite、Bookmark の変更は
画面とサーバーの両方で無効になります
port を変える場合は ``--port 8051`` のように指定します


Optuna を用いたパラメータ探索
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

コマンドは以下です

.. code-block:: shell

    python3 -m ahclib opt [--no-wilcoxon] [-a] [--tailscale]
    python3 -m ahclib opt --vis [--tailscale]

**オプション**

- ``--no-wilcoxon`` : ``WilcoxonPruner`` を無効にする。既定では有効
- ``-a``, ``--auto_sampler`` : ``auto_sampler`` を使う。指定しないときは ``TPESampler`` を使う
- ``--vis`` : 最適化やコンパイルを行わず、保存済み study の Optuna Dashboard だけを起動する
- ``--tailscale`` : Optuna Dashboard を Tailscale の tailnet 内だけに共有する

全 study は ``./ahclib_results/optimizer_results/optuna-journal.log`` に保存される。
同じ storage を共有するため、Dashboard の study 一覧から別の ``study_name`` も表示できる。
旧版が作成した ``ahclib_optuna_*`` PostgreSQL database がローカルにある場合は、未登録の study を journal へ非破壊でコピーする。
``Ctrl-C`` では実行中 solver と optimizer session を順に停止し、実行中 trial を ``FAIL`` として確定する。
強制終了などでworkerだけが先に消えた場合も、worker情報を持つ孤立 ``RUNNING`` trial は次回起動時に ``FAIL`` へ回収する。

最適化終了時には ``./ahclib_results/optimizer_results/<study_name>/`` に以下を保存する。

- ``result.txt`` : best trial
- ``trials.csv`` : 全 trial の値、parameter、user attribute
- ``study.json`` : best trial、trial state の件数、直近実行の設定
- ``images/`` : Optuna のグラフ
- solver source と使用した settings file のスナップショット
- ``runs/<timestamp>/`` : 各 optimizer 実行時点の ``result.txt``、``trials.csv``、``study.json``、source/settings

``WilcoxonPruner`` は各ケースの score を、そのケースの固定 ID を step として ``trial.report`` する。
評価順は trial ごとにシャッフルされる。``should_prune()`` が真になった場合、実行中 solver を終了し、
完了済みケースから ``get_score`` で推定した目的値を返す。この挙動は WilcoxonPruner の推奨方法に合わせたもので、
ただし推定値が現在の best を更新する場合は、未評価ケースを含む trial が best になることを防ぐため
``TrialPruned`` とする。途中停止の有無と評価ケース数は ``ahclib_wilcoxon_stopped`` /
``ahclib_evaluated_cases`` user attribute に記録される。


スマホから vis と Optuna 結果を非公開で見る
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``--tailscale`` を指定すると、通常の vis または Optuna Dashboard をローカルで
動かしたまま、`Tailscale Serve
<https://tailscale.com/docs/features/tailscale-serve>`_ 経由で自分の
tailnet 内だけに共有される。インターネット一般には公開されない。

個人・非商用で使う場合、Tailscale の `Personal plan
<https://tailscale.com/pricing>`_ を無料で利用できる。

初回導入
""""""""

1. ahclibを実行するLinux環境へTailscaleをインストールする。

   - `Linuxインストール手順 <https://tailscale.com/docs/install/linux>`_

   WSLとUbuntu/Linuxのどちらも、公式のインストールscriptを使う場合は
   以下になる。

   .. code-block:: shell

       curl -fsSL https://tailscale.com/install.sh | sh
       sudo tailscale up
       tailscale status

   ``tailscale status`` に自分の端末が表示されれば準備完了である。
   daemonへ接続できない場合は、次を実行してから ``sudo tailscale up`` を
   やり直す。

   .. code-block:: shell

       sudo systemctl enable --now tailscaled

   Windows側にインストールしたTailscaleは、WSL内の ``tailscale`` command
   とは別物である。ahclibをWSLで動かす場合は、WSL内にもインストールする。
   別PCのUbuntu/Linuxで動かす場合も、そのPCへ同じ手順でインストールする。

2. 表示に使うスマホへTailscaleをインストールする。

   - `iPhone / iPad <https://tailscale.com/download/ios>`_
   - `Android <https://tailscale.com/download/android>`_

3. PCとスマホを同じTailscale accountでログインし、両方が同じtailnetに
   表示されることを確認する。

使い方
""""""

最適化しながら表示する場合:

.. code-block:: shell

    python3 -m ahclib opt --tailscale

保存済みの結果だけを表示する場合:

.. code-block:: shell

    python3 -m ahclib opt --vis --tailscale

保存済みのテスト結果を通常の vis で表示する場合:

.. code-block:: shell

    python3 -m ahclib vis --tailscale

通常の vis は共有時だけ読み取り専用になります

初回はTailscale ServeのHTTPSを有効にするための同意URLがログに表示される。
そのURLをPCで開いて許可すると、次のようなスマホ用URLが表示される。

.. code-block:: text

    - private URL   : https://<PC名>.<tailnet名>.ts.net
    - access scope  : Tailscale tailnet only (not public)

スマホのTailscaleを接続状態にして、この ``private URL`` をbrowserで開く。
終了時は従来どおりEnterまたは ``Ctrl-C`` を使う。ahclibはforegroundの
Tailscale Serveも同時に停止するため、共有設定は常駐しない。

セキュリティ上の注意
""""""""""""""""""""""

- 公開機能である ``tailscale funnel`` は使用しない。ahclibが起動するのは
  tailnet限定の ``tailscale serve`` だけである
- ``--tailscale`` を付けない通常実行では、外部共有は一切起動しない
- HTTPS 証明書の発行に使う Tailscale の端末名は公開 ledger に記録されるため、端末名へ機密情報を含めない
- コンテスト中はtailnetへ他人を招待せず、自分の端末だけを登録する
- スマホ紛失時はTailscale管理画面からその端末を削除する
- 大会ごとの外部サービス利用規約も確認する


設定ファイル
-------------

設定ファイル ``ahc_settings.py`` 中の ``AHCSettings`` クラスに以下の情報を書いてください

* スレッド数 (``njobs``)

  - (パソコンの最大スレッド数-1)との ``min`` がとられる

* ファイル名 (``filename``)

* コンパイルコマンド (``compile_command``)

  - コンパイルする必要が無いときは、``None`` とする

* 実行コマンド (``execute_command``)

* 入力ファイル (``input_file_names``)

  - ``list[str]`` の形式で書く

* 制限時間 (``timeout``)

  - ``ms`` 単位で指定する
  - 指定しないときは ``None`` とする
  - 各テストでメモリを多く使う場合など、正確さに欠けることがある点に注意

* 集計関数 (``get_score``)

  - 例: 平均など

* スコアの型 (``is_int``)

  - スコアが整数なら ``True``、小数なら ``False``

* 方向 (``direction``)

  - ``minimize`` か ``maximize``
  - 相対スコアの計算と Optuna の最適化方向の両方で使われる

* 相対スコアの計算 (``use_relative_score``)

  - ``True`` のとき、相対スコアをログと csv に出力する

* 相対スコアの基準 (``pre_dir_name``)

  - 相対スコアの基準にする過去結果ディレクトリ名を ``./ahclib_results/`` 以下から指定する


例:

.. code-block:: python

    njobs = 127
    filename = "./main.cpp"
    compile_command = "g++ ./main.cpp -O2 -std=c++20 -o a.out -I./../../../Library_cpp"
    execute_command = "./a.out"
    input_file_names = [f"./in/{str(i).zfill(4)}.txt" for i in range(100)]
    timeout = None
    is_int = True
    direction = "maximize"
    use_relative_score = False
    pre_dir_name = ""

    def get_score(scores: list[float]) -> float:
        return sum(scores) / len(scores)


Optuna を用いたパラメータ探索用の設定
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``study_name``

  - 全 study が ``./ahclib_results/optimizer_results/optuna-journal.log`` を共有する
  - 既に同名の study がある場合、その study が利用される

* Journal storage

  - ``ahclib_results`` 以下のローカルファイルへ最適化履歴を保存する
  - 同一ホスト上の複数 optimizer process から共有する
  - WSL の ``/mnt/c`` と Linux/Ubuntu のローカル filesystem の両方で、symbolic link に依存しない lock file を使用する
  - PostgreSQL のセットアップは不要

* ``direction``

  - ``minimize`` か ``maximize``

* optuna の試行回数 (``n_trials``)

* optuna の実行時間制限 minutes (``optuna_timeout``)

  - ``None`` の場合は時間制限なし
  - ``n_trials`` と ``optuna_timeout`` のどちらか先に到達した時点で終了する

* Optuna session 数 (``njobs_optuna``)

  - ``min(njobs_optuna, cpu_count - 1, n_trials)`` 個の独立 process を起動する
  - 各 process は同じ study と JournalStorage を共有し、``n_jobs=1`` で最適化する
  - ``n_trials`` は process 間に分配され、全 process の合計試行回数になる
  - sessionごとの開始・終了を番号付きで表示し、同じ初期化messageは繰り返さない

* シード (``optuna_seed``)

  - sampler のシードと、``WilcoxonPruner`` 使用時の trial ごとの入力順シャッフルの基準 seed に使われる
  - ``None`` も指定できる

* ランダム探索の試行回数 (``optuna_n_startup_trials``)

  - ``TPESampler`` がランダムに探索する試行回数

* 初期評価するパラメータ (``optuna_init_trials``)

  - 探索の起点として最初に評価するパラメータ値の辞書のリストを指定する
  - 各辞書は ``study.enqueue_trial`` に渡される

* 推定するもの

  .. code-block:: python

      def objective(trial: optuna.trial.Trial) -> tuple:

  - 返り値のタプルはコマンドライン引数として渡す順番にする


例: 初期温度を探索する

.. code-block:: python

  study_name = "test"
  direction = "minimize"
  n_trials = 50
  optuna_timeout = None  # 例: 60 なら 1 時間
  njobs_optuna = 1
  optuna_seed = 23
  optuna_n_startup_trials = 10
  optuna_init_trials = []

  def objective(trial: optuna.trial.Trial) -> tuple:
      start_temp = trial.suggest_float("start_temp", 1, 1e9, log=True)
      return start_temp,  # タプルで返す

.. code-block:: cpp

  double start_temp;

  int main(int argc, char *argv[]) {
      start_temp = std::stod(argv[1]);  // argv[1], ... に objective で返した値が格納されている
      solve();
      return 0;
  }

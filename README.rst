AHC Tools
===========

`titan23 <https://atcoder.jp/users/titan23?contestType=heuristic>`_  が使用している、AHC のツールです。
ありえないバグがあるかもしれません。ご注意ください。

`view on github <https://github.com/titan-23/ahctools/tree/main>`_


インストール方法
-------------------

インストールには以下のコマンドを実行してください

.. code-block:: shell

    python3 -m pip install git+https://github.com/titan-23/ahctools

アンインストールするときは以下です

.. code-block:: shell

    python3 -m pip uninstall ahctools

使い方
-------

初期設定
~~~~~~~~~~~~~~~~~~

作業ディレクトリで以下のコマンドを実行し、設定ファイル ``ahc_settings`` ファイルを生成します

.. code-block:: shell

    python3 -m ahctools setup



並列実行
~~~~~~~~~~~~~~~~~~

``njobs`` 数のスレッドを立ち上げて実行します。結果を記録した csv ファイルと実行ソースファイルが ``./ahctools_results/`` ディレクトリに保存されます

コマンドは以下です

.. code-block:: shell

    python3 -m ahctools test [-c] [-v] [-r]

**オプション**

- ``-c`` : コンパイルします
- ``-v`` : ログを表示します(推奨)
- ``-r`` : 標準出力と標準エラー出力をすべて保存します


Optuna を用いたパラメータ探索
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

コマンドは以下です

.. code-block:: shell

    python3 -m ahctools opt


設定ファイル
-------------

設定ファイル``ahc_settings``中の``AHCSettings``クラスに以下の情報を書いてください

* スレッド数 (``njobs``)
  - (パソコンの最大スレッド数-1)との ``min`` がとられる
* ファイル名 (``filename``)
* コンパイルコマンド (``compile_command``)
  - コンパイルする必要が無いときは、``None`` とする
* 実行コマンド (``execute_command``)
* 入力ファイル (``input_file_names``)
  - ``list[str]``の形式で書く
* 制限時間 (``timeout``)
  - 指定しないときは ``None`` とする
  - 各テストでメモリを多く使う場合など、正確さに欠けることがある点に注意
* 集計関数 (``get_score``)
  - 例: 平均など

.. code-block:: python

    def objective(trial: optuna.trial.Trial) -> tuple:


例:
.. code-block:: python
    njobs = 127
    filename = "./main.cpp"
    compile_command = "g++ ./main.cpp -O2 -std=c++20 -o a.out -I./../../../Library_cpp"
    execute_command = "./a.out"
    input_file_names = [f"./in/{str(i).zfill(4)}.txt" for i in range(100)]
    timeout = 3100

    def get_score(scores: list[float]) -> float:
        return sum(scores) / len(scores)


Optuna を用いたパラメータ探索用の設定
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``study_name``

  - ``study_name`` が既にある場合、そのデータベースが利用される

* ``direction``

  - ``minimize`` か ``maximize``

* optuna の試行回数 (``n_trials``)

  - 例: ``50``

* optuna のスレッド数 (``n_jobs_optuna``)

  - 例: ``1``

* 推定するもの

  .. code-block:: python

      def objective(trial: optuna.trial.Trial) -> tuple:

  - 返り値のタプルはコマンドライン引数として渡す順番にする

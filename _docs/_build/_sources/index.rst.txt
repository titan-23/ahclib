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

* スレッド数 (``njobs``):

  - 例: ``127``
  - (パソコンの最大スレッド数-1)との ``min`` がとられる

* ファイル名 (``filename``):

  - 例: ``"./main.cpp"``

* コンパイルコマンド (``compile_command``):

  - 例: ``"g++ ./main.cpp -O2 -std=c++20"``
  - コンパイルす必要が無いときは、``None`` とする

* 実行コマンド (``execute_command``):

  - 例: ``"./a.out"`` など

* 入力ファイル (``input_file_names``):

  - 例: ``[f'./in/{str(i).zfill(4)}.txt' for i in range(100)]``

* 制限時間 (``timeout``):

  - 例: ``2000``
  - 指定しないときは ``None`` とする
  - 各テストでメモリを多く使う場合など、正確さに欠ける場合があります

* 集計関数 (``get_score``):

  - 例: 平均など

Optuna を用いたパラメータ探索用の設定
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``study_name``:

  - ``study_name`` が既にある場合、そのデータベースが利用される

* ``direction``:

  - ``minimize`` か ``maximize``

* optuna の試行回数 (``n_trials``):

  - 例: ``50``

* optuna のスレッド数 (``n_jobs_optuna``):

  - 例: ``1``

* 推定するもの:

  .. code-block:: python

      def objective(trial: optuna.trial.Trial) -> tuple:

  - 返り値のタプルはコマンドライン引数として渡す順番にする

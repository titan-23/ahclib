AHC Lib
===========

`titan23 <https://atcoder.jp/users/titan23?contestType=heuristic>`_  が使用している、AHC のツールです。
ありえないバグがあるかもしれません。ご注意ください。

`View on GitHub <https://github.com/titan-23/ahclib/tree/main>`_

`View on PyPI <https://pypi.org/project/ahclib/>`_


使い方
-------

初期設定
~~~~~~~~~~~~~~~~~~

作業ディレクトリで以下のコマンドを実行し、設定ファイル ``ahc_settings`` ファイルを生成します

.. code-block:: shell

    python3 -m ahclib setup



並列実行
~~~~~~~~~~~~~~~~~~

``njobs`` 数のスレッドを立ち上げて実行します。結果を記録した csv ファイルと実行ソースファイルが ``./ahclib_results/`` ディレクトリに保存されます

コマンドは以下です

.. code-block:: shell

    python3 -m ahclib test [-c] [-v] [-r]

**オプション**

- ``-c`` : コンパイルします
- ``-v`` : ログを表示します(推奨)
- ``-r`` : 標準出力と標準エラー出力をすべて保存します


Optuna を用いたパラメータ探索
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

コマンドは以下です

.. code-block:: shell

    python3 -m ahclib opt


設定ファイル
-------------

設定ファイル ``ahc_settings`` 中の ``AHCSettings`` クラスに以下の情報を書いてください

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


例:

.. code-block:: python

    njobs = 127
    filename = "./main.cpp"
    compile_command = "g++ ./main.cpp -O2 -std=c++20 -o a.out -I./../../../Library_cpp"
    execute_command = "./a.out"
    input_file_names = [f"./in/{str(i).zfill(4)}.txt" for i in range(100)]
    timeout = None

    def get_score(scores: list[float]) -> float:
        return sum(scores) / len(scores)


Optuna を用いたパラメータ探索用の設定
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``study_name``

  - ``study_name`` が既にある場合、そのデータベースが利用される

* ``direction``

  - ``minimize`` か ``maximize``

* optuna の試行回数 (``n_trials``)

* optuna のスレッド数 (``n_jobs_optuna``)

* 推定するもの

  .. code-block:: python

      def objective(trial: optuna.trial.Trial) -> tuple:

  - 返り値のタプルはコマンドライン引数として渡す順番にする


例: 初期温度を探索する

.. code-block:: python

  study_name = "test"
  direction = "minimize"
  n_trials = 50
  n_jobs_optuna = 1

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

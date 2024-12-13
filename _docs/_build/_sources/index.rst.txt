AHC Tools
=========

AHC並列実行のツールです。

## インストール方法

インストールには以下のコマンドを実行してください。

.. code-block:: shell

    $ python3 -m pip install git+https://github.com/titan-23/ahctools

アンインストールするときは以下です。

.. code-block:: shell

    $ python3 -m pip uninstall git+https://github.com/titan-23/ahctools

## 実行方法

### 並列実行

以下のコマンドで実行できます。

.. code-block:: shell

    $ python3 -m ahctools test [-c] [-v] [-r]

コマンドオプション:
- ``-c`` コンパイルします。
- ``-v`` ログを表示します。
- ``-r`` 標準出力と標準エラー出力をファイルに保存します。オプションを指定しない場合、結果を記録したcsvファイルのみを得られます。

### optunaを用いたパラメータ探索

以下のコマンドで実行できます。

.. code-block:: shell

    $ python3 -m ahctools opt

## 設定方法

### 共通 / `test`

- スレッド数 `njobs`
    - 例: `127`
- ファイル名 `filename`
    - 例: `"./main.cpp"`
- コンパイルコマンド `compile_command`
    - 例: `"g++ ./main.cpp -O2 -std=c++20"`
- 実行コマンド `execute_command`
    - 例: `"./a.out"` など
- 入力ファイル `input_file_names`
    - 例: `[f'./in/{str(i).zfill(4)}.txt' for i in range(100)]`
- 制限時間 `timeout`
    - 例: `2000`
    - 指定しないときは `None` としてください。
- 集計関数 `get_score`
    - 平均など。

### `optimizer`
- `study_name`
    - `study_name` が既にある場合、そのデータベースが利用される。
- `direction`
    - `minimize` か `maximize`
- optuna の試行回数 `n_trials`
- optuna のスレッド数 `n_jobs_optuna`
- 推定するもの
    - `objective(trial: optuna.trial.Trial) -> tuple:`
    - 返り値のタプルはコマンドライン引数として渡す順番にする

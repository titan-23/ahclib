/**
 * @file ida.cpp
 * @author titan23
 * @brief
 *  ida探索を用いた厳密解法
 *  N > 4 のときはメモリに注意
 *    N=5,4GB程度
 *
 * ref: https://computerpuzzle.net/puzzle/15puzzle/index.html
 */

#pragma GCC target("avx2")
#pragma GCC optimize("O3")
#pragma GCC optimize("unroll-loops")

#include <iostream>
#include <vector>
#include <chrono>
#include <cassert>
#include <stack>
#include <queue>
#include <cstring>
#include <algorithm>

#include <ext/pb_ds/assoc_container.hpp>
#include <ext/pb_ds/hash_policy.hpp>

using namespace std;

// Timer
namespace titan23 {

  /**
   * @brief 時間計測クラス
   */
  class Timer {
   private:
    chrono::time_point<chrono::high_resolution_clock> start_timepoint;

   public:
    Timer() : start_timepoint(chrono::high_resolution_clock::now()) {}

    /**
     * @brief リセットする
     */
    void reset() {
      start_timepoint = chrono::high_resolution_clock::now();
    }

    /**
     * @brief 経過時間[ms]を返す
     */
    double elapsed() {
      auto end_timepoint = chrono::high_resolution_clock::now();
      auto start = chrono::time_point_cast<chrono::microseconds>(start_timepoint).time_since_epoch().count();
      auto end = chrono::time_point_cast<chrono::microseconds>(end_timepoint).time_since_epoch().count();
      return (end - start) * 0.001;
    }
  };
}

// StatePool
namespace titan23 {

  /**
   * @brief ノードプールクラス
   * @fn init(const unsigned int n): n要素確保する。
   * @fn T* get(int i) const: iに対応するTのポインタを返す。
   * @fn void del(int state_id): state_idに対応するTを仮想的に削除する。
   * @fn int gen(): Tを仮想的に作成し、それに対応するidを返す。
   * @fn int copy(int i): iに対応するTをコピーし、コピー先のidを返す。
   */
  template<typename T>
  class StatePool {
   public:
    vector<T*> pool;
    stack<int> unused_indx;

   public:
    StatePool() {}
    StatePool(const unsigned int n) {
      init(n);
    }

    void init(const unsigned int n) {
      for (int i = 0; i < n; ++i) {
        T* state = new T;
        pool.emplace_back(state);
        unused_indx.emplace(i);
      }
    }

    T* get(int id) const {
      assert(0 <= id && id < pool.size());
      return pool[id];
    }

    void del(int id) {
      assert(0 <= id && id < pool.size());
      unused_indx.emplace(id);
    }

    int gen() {
      int state_id;
      if (unused_indx.empty()) {
        T* state = new T;
        state_id = pool.size();
        pool.emplace_back(state);
      } else {
        state_id = unused_indx.top();
        unused_indx.pop();
      }
      return state_id;
    }

    int copy(int id) {
      int new_id = gen();
      pool[id]->copy(pool[new_id]);
      return new_id;
    }
  };
}

// Action
namespace titan23 {

  enum class Action { U, R, D, L };
  ostream& operator<<(ostream& os, const Action &action) {
    switch (action) {
      case Action::U: os << 'U'; break;
      case Action::R: os << 'R'; break;
      case Action::D: os << 'D'; break;
      case Action::L: os << 'L'; break;
      default: assert(false);
    }
    return os;
  }

  Action get_rev_action(const Action &action) {
    switch (action) {
      case Action::U: return Action::D;
      case Action::D: return Action::U;
      case Action::R: return Action::L;
      case Action::L: return Action::R;
    }
    assert(false);
  }
}

// Random
namespace titan23 {

  struct Random {

   private:
    unsigned int _x, _y, _z, _w;

    unsigned int _xor128() {
      const unsigned int t = _x ^ (_x << 11);
      _x = _y;
      _y = _z;
      _z = _w;
      _w = (_w ^ (_w >> 19)) ^ (t ^ (t >> 8));
      return _w;
    }

   public:
    Random() : _x(123456789),
               _y(362436069),
               _z(521288629),
               _w(88675123) {}

    double random() { return (double)(_xor128()) / 0xFFFFFFFF; }

    int randint(const int end) {
      assert(0 <= end);
      return (((unsigned long long)_xor128() * (end+1)) >> 32);
    }

    int randint(const int begin, const int end) {
      assert(begin <= end);
      return begin + (((unsigned long long)_xor128() * (end-begin+1)) >> 32);
    }

    unsigned long long randrand() {
      return (unsigned long long)_xor128() * (unsigned long long)_xor128();
    }

    int randrange(const int end) {
      assert(0 < end);
      return (((unsigned long long)_xor128() * end) >> 32);
    }

    int randrange(const int begin, const int end) {
      assert(begin < end);
      return begin + (((unsigned long long)_xor128() * (end-begin)) >> 32);
    }

    double randdouble(const double begin, const double end) {
      assert(begin < end);
      return begin + random() * (end-begin);
    }

    template <typename T>
    void shuffle(vector<T> &a) {
      int n = (int)a.size();
      for (int i = 0; i < n-1; ++i) {
        int j = randrange(i, n);
        swap(a[i], a[j]);
      }
    }
  };
} // namespace titan23

std::string zfill(const int num, const int width) {
  std::string str = std::to_string(num);
  return std::string(width - str.size(), '0') + str;
}

#define rep(i, n) for (int i = 0; i < (n); ++i)
using HashType = unsigned long long;

int N;
vector<vector<int>> A;

void input() {
  cin >> N;
  A.resize(N, vector<int>(N));
  rep(i, N) rep(j, N) {
    cin >> A[i][j];
  }
}

namespace titan23 {

namespace IDA {
  vector<uint8_t> revB;
  vector<vector<HashType>> hash_rand;
  __gnu_pbds::gp_hash_table<HashType, int> wd_hash;
  vector<vector<HashType>> wd_rand;
  vector<HashType> pos_hash_rand;
  vector<vector<vector<Action>>> trans;

  void init() {
    trans.resize(N*N, vector<vector<Action>>(5));
    // trans[ij][action];
    rep(ij, N*N) rep(k, 5) {
      int i = ij/N, j = ij%N;
      if (i-1 >= 0) trans[ij][k].emplace_back(Action::U);
      if (i+1 < N)  trans[ij][k].emplace_back(Action::D);
      if (j-1 >= 0) trans[ij][k].emplace_back(Action::L);
      if (j+1 < N)  trans[ij][k].emplace_back(Action::R);
      if (k < 4) {
        Action rev = static_cast<Action>(k);
        trans[ij][k].erase(remove(trans[ij][k].begin(), trans[ij][k].end(), get_rev_action(rev)), trans[ij][k].end());
      }
    }

    vector<vector<uint8_t>> B(N, vector<uint8_t>(N));
    revB.resize(N*N);
    rep(i, N) rep(j, N) {
      B[i][j] = i*N+j+1;
      if (i == N-1 && j == N-1) B[i][j] = 0;
    }
    rep(i, N) rep(j, N) {
      revB[B[i][j]] = j*N+i;
    }

    titan23::Random r;
    hash_rand.resize(N*N, vector<HashType>(N*N));
    rep(ij, N*N) rep(num, N*N) {
      hash_rand[ij][num] = r.randrand();
    }
  }

  struct State {
    vector<uint8_t> wd;
    short pos;
    HashType hash;
    State() {}

    void copy(State* new_state) const {
      new_state->wd = this->wd;
      new_state->pos = this->pos;
      new_state->hash = this->hash;
    }

    void init() {
      wd.resize(N*N, 0);
      titan23::Random r;
      wd_rand.resize(N*N, vector<HashType>(N+1));
      rep(ij, N*N) rep(k, N+1) {
        wd_rand[ij][k] = r.randrand();
      }
      pos_hash_rand.resize(N);
      rep(i, N) {
        pos_hash_rand[i] = r.randrand();
      }
    }

    void print() const {
      rep(i, N) {
        rep(j, N) {
          cout << wd[i*N+j] << ' ';
        }
        cout << endl;
      }
      cout << endl;
    }

    void calc_hash() {
      hash = pos_hash_rand[pos];
      rep(ij, N*N) {
        hash ^= wd_rand[ij][wd[ij]];
      }
    }

    HashType try_up(const int j) const {
      HashType h = hash;
      h ^= wd_rand[pos*N+j][wd[pos*N+j]];
      h ^= wd_rand[(pos-1)*N+j][wd[(pos-1)*N+j]];
      h ^= wd_rand[pos*N+j][wd[pos*N+j]+1];
      h ^= wd_rand[(pos-1)*N+j][wd[(pos-1)*N+j]-1];
      h ^= pos_hash_rand[pos];
      h ^= pos_hash_rand[pos-1];
      return h;
    }

    HashType try_down(const int j) const {
      HashType h = hash;
      h ^= wd_rand[pos*N+j][wd[pos*N+j]];
      h ^= wd_rand[(pos+1)*N+j][wd[(pos+1)*N+j]];
      h ^= wd_rand[pos*N+j][wd[pos*N+j]+1];
      h ^= wd_rand[(pos+1)*N+j][wd[(pos+1)*N+j]-1];
      h ^= pos_hash_rand[pos];
      h ^= pos_hash_rand[pos+1];
      return h;
    }

    void apply_up(const int i) {
      hash ^= wd_rand[pos*N+i][wd[pos*N+i]];
      hash ^= wd_rand[(pos-1)*N+i][wd[(pos-1)*N+i]];
      hash ^= wd_rand[pos*N+i][wd[pos*N+i]+1];
      hash ^= wd_rand[(pos-1)*N+i][wd[(pos-1)*N+i]-1];
      hash ^= pos_hash_rand[pos];
      hash ^= pos_hash_rand[pos-1];
      ++wd[pos*N+i];
      --wd[(pos-1)*N+i];
      --pos;
    }

    void apply_down(const int i) {
      hash ^= wd_rand[pos*N+i][wd[pos*N+i]];
      hash ^= wd_rand[(pos+1)*N+i][wd[(pos+1)*N+i]];
      hash ^= wd_rand[pos*N+i][wd[pos*N+i]+1];
      hash ^= wd_rand[(pos+1)*N+i][wd[(pos+1)*N+i]-1];
      hash ^= pos_hash_rand[pos];
      hash ^= pos_hash_rand[pos+1];
      ++wd[pos*N+i];
      --wd[(pos+1)*N+i];
      ++pos;
    }

    void apply_left(const int i) {
      apply_up(i);
    }

    void apply_right(const int i) {
      apply_down(i);
    }

    HashType tohash() const {
      return hash;
    }
  };

  void calc_WD() {
    StatePool<State> pool;
    int state = pool.gen();
    pool.get(state)->init();

    rep(i, N) pool.get(state)->wd[i*N+i] = N;
    pool.get(state)->wd[(N-1)*N+(N-1)] = N-1;
    pool.get(state)->pos = N-1;
    pool.get(state)->calc_hash();

    wd_hash[pool.get(state)->tohash()] = 0;
    queue<pair<int, int>> qu;
    qu.emplace(0, state);
    while (!qu.empty()) {
      int dist = qu.front().first;
      state = qu.front().second;
      qu.pop();
      if (pool.get(state)->pos != 0) { // up
        rep(j, N) {
          if (pool.get(state)->wd[(pool.get(state)->pos-1)*N+j]) {
            HashType h = pool.get(state)->try_up(j);
            if (wd_hash.find(h) != wd_hash.end()) continue;
            int new_state = pool.copy(state);
            pool.get(new_state)->apply_up(j);
            wd_hash[pool.get(new_state)->tohash()] = dist+1;
            qu.emplace(dist+1, new_state);
          }
        }
      }

      if (pool.get(state)->pos != N-1) { // down
        rep(j, N) {
          if (pool.get(state)->wd[(pool.get(state)->pos+1)*N+j]) {
            HashType h = pool.get(state)->try_down(j);
            if (wd_hash.find(h) != wd_hash.end()) continue;
            int new_state = pool.copy(state);
            pool.get(new_state)->apply_down(j);
            wd_hash[pool.get(new_state)->tohash()] = dist+1;
            qu.emplace(dist+1, new_state);
          }
        }
      }

      pool.del(state);
    }
    cerr << wd_hash.size() << endl;
  }

  struct Node {
    State state_memo_ud, state_memo_lr;
    HashType hash;
    vector<uint8_t> field;
    vector<Action> history;
    int dist_true;
    int inv_ud, inv_lr, inv_dist, walking_dist;
    int zi, zj;
    Node() {}

    int get_inversion_lr() const {
      int cnt = 0;
      rep(i, N*N) {
        if (field[(i%N)*N+(i/N)] == 0) continue;
        for (int j = i+1; j < N*N; ++j) {
          if (field[(j%N)*N+(j/N)] == 0) continue;
          if (revB[field[(i%N)*N+(i/N)]] > revB[field[(j%N)*N+(j/N)]]) {
            ++cnt;
          }
        }
      }
      return cnt;
    }

    int get_inversion_ud() const {
      int cnt = 0;
      rep(i, N*N) {
        if (field[i] == 0) continue;
        for (int j = i+1; j < N*N; ++j) {
          if (field[j] == 0) continue;
          if (field[i] > field[j]) {
            ++cnt;
          }
        }
      }
      return cnt;
    }

    void calc_preddist() {
      inv_ud = get_inversion_ud();
      inv_lr = get_inversion_lr();
      inv_dist = inv_ud/(N-1)+inv_ud%(N-1) + inv_lr/(N-1)+inv_lr%(N-1);

      walking_dist = 0;
      {
        fill(state_memo_ud.wd.begin(), state_memo_ud.wd.end(), 0);
        state_memo_ud.pos = zi;
        rep(i, N) rep(j, N) {
          uint8_t val = field[i*N+j];
          if (val == 0) continue;
          int vi = (val-1) / N;
          state_memo_ud.wd[i*N+vi]++;
        }
        state_memo_ud.calc_hash();
        HashType h = state_memo_ud.tohash();
        walking_dist += wd_hash[h];
      }
      {
        fill(state_memo_lr.wd.begin(), state_memo_lr.wd.end(), 0);
        state_memo_lr.pos = zj;
        rep(i, N) rep(j, N) {
          uint8_t val = field[i*N+j];
          if (val == 0) continue;
          int vj = (val-1) % N;
          state_memo_lr.wd[j*N+vj]++;
        }
        state_memo_lr.calc_hash();
        HashType h = state_memo_lr.tohash();
        walking_dist += wd_hash[h];
      }
    }

    int get_preddist() const {
      return max(inv_dist, walking_dist);
    }

    void move(const Action &action) {
      // ni, nj
      int ni = zi, nj = zj;
      switch (action) {
      case Action::D: ++ni; break;
      case Action::R: ++nj; break;
      case Action::U: --ni; break;
      case Action::L: --nj; break;
      }

      // inv_dist
      if (action == Action::D) {
        const uint8_t fn = field[ni*N+nj];
        for (int ind = zi*N+zj+1; ind < ni*N+nj; ++ind) {
          if (field[ind] > fn) --inv_ud;
          else ++inv_ud;
        }
      } else if (action == Action::R) {
        const uint8_t fn = revB[field[ni*N+nj]];
        for (int ind = zj*N+zi+1; ind < nj*N+ni; ++ind) {
          if (revB[field[(ind%N)*N+(ind/N)]] > fn) --inv_lr;
          else ++inv_lr;
        }
      } else if (action == Action::U) {
        const uint8_t fn = field[ni*N+nj];
        for (int ind = ni*N+nj+1; ind < zi*N+zj; ++ind) {
          if (field[ind] < fn) --inv_ud;
          else ++inv_ud;
        }
      } else {
        const uint8_t fn = revB[field[ni*N+nj]];
        for (int ind = nj*N+ni+1; ind < zj*N+zi; ++ind) {
          if (revB[field[(ind%N)*N+(ind/N)]] < fn) --inv_lr;
          else ++inv_lr;
        }
      }
      inv_dist = inv_ud/(N-1)+inv_ud%(N-1) + inv_lr/(N-1)+inv_lr%(N-1);

      // walking_dist
      switch (action) {
      case Action::D:
        walking_dist -= wd_hash[state_memo_ud.tohash()];
        state_memo_ud.apply_down((field[ni*N+nj]-1)/N);
        walking_dist += wd_hash[state_memo_ud.tohash()];
        break;
      case Action::R:
        walking_dist -= wd_hash[state_memo_lr.tohash()];
        state_memo_lr.apply_right((field[ni*N+nj]-1)%N);
        walking_dist += wd_hash[state_memo_lr.tohash()];
        break;
      case Action::U:
        walking_dist -= wd_hash[state_memo_ud.tohash()];
        state_memo_ud.apply_up((field[ni*N+nj]-1)/N);
        walking_dist += wd_hash[state_memo_ud.tohash()];
        break;
      case Action::L:
        walking_dist -= wd_hash[state_memo_lr.tohash()];
        state_memo_lr.apply_left((field[ni*N+nj]-1)%N);
        walking_dist += wd_hash[state_memo_lr.tohash()];
        break;
      default: assert(false);
      }

      // hash
      hash ^= hash_rand[zi*N+zj][field[zi*N+zj]];
      hash ^= hash_rand[zi*N+zj][field[ni*N+nj]];
      hash ^= hash_rand[ni*N+nj][field[ni*N+nj]];
      hash ^= hash_rand[ni*N+nj][field[zi*N+zj]];

      swap(field[zi*N+zj], field[ni*N+nj]);
      zi = ni;
      zj = nj;
    }

    void rollback(const Action &action) {
      --dist_true;
      history.pop_back();
      move(get_rev_action(action));
    }

    void apply_op(const Action &action) {
      ++dist_true;
      history.emplace_back(action);
      move(action);
    }

    vector<Action>& get_actions() const {
      return trans[zi*N+zj][history.empty() ? 4 : static_cast<int>(history.back())];
    }

    bool done() const {
      return get_preddist() == 0;
    }

    void print() const {
      rep(i, N) {
        rep(j, N) {
          cout << zfill(field[i*N+j], 2) << ' ';
        }
        cout << endl;
      }
      cout << endl;
    }

    int get_dist() const {
      return dist_true;
    }

    void init() {
      field.resize(N*N);
      history.clear();
      hash = 0;
      dist_true = 0;
      rep(i, N) rep(j, N) {
        field[i*N+j] = A[i][j];
        hash ^= hash_rand[i*N+j][field[i*N+j]];
        if (field[i*N+j] == 0) {
          zi = i;
          zj = j;
        }
      }
      state_memo_ud.wd.resize(N*N, 0);
      state_memo_lr.wd.resize(N*N, 0);
      calc_preddist();
    }
  };

  Node node;
  vector<Action> best_history;
  int dfs_limit;
  __gnu_pbds::gp_hash_table<HashType, int> visit;

  bool dfs() {
    if (node.get_dist() + node.get_preddist() > dfs_limit) return false;
    if (node.done()) {
      best_history = node.history;
      return true;
    }
    auto it = visit.find(node.hash);
    if (it != visit.end() && it->second <= node.get_dist()) {
      return false;
    }
    if (it == visit.end()) {
      if (visit.size() < 1e7) visit[node.hash] = node.get_dist();
    } else {
      it->second = node.get_dist();
    }
    const vector<Action> &actions = node.get_actions();
    for (const Action &action: actions) {
      node.apply_op(action);
      if (dfs()) return true;
      node.rollback(action);
    }
    return false;
  }

  vector<Action> run() {
    node.init();
    if (node.get_preddist() == 0) return {};
    dfs_limit = node.get_preddist();
    if (dfs_limit%2 != node.get_inversion_ud()%2) ++dfs_limit;

    titan23::Timer timer;
    for (; ; dfs_limit += 2) {
      cerr << "dfs_limit=" << dfs_limit << endl;
      node.init();
      visit.clear();
      if (dfs()) return best_history;
      cerr << timer.elapsed()/1000 << " sec." << endl;
    }
  }
}
}

void solve() {
  assert(N <= 4);  // use too large memory.

  titan23::Timer timer;

  titan23::IDA::init();
  titan23::IDA::calc_WD();
  cerr << timer.elapsed()/1000 << " sec." << endl;

  vector<titan23::Action> ans = titan23::IDA::run();

  cout << ans.size() << endl;
  for (const titan23::Action &action: ans) {
    cout << action;
  }
  cout << endl;
  cerr << timer.elapsed()/1000 << " sec." << endl;
}

int main() {
  input();
  solve();
  return 0;
}
/*
./a.out < testcase2.txt
20.046 sec.
dfs_limit=70
1.9e-05 sec.
dfs_limit=72
7.9e-05 sec.
dfs_limit=74
0.000559 sec.
dfs_limit=76
0.003889 sec.
dfs_limit=78
0.026345 sec.
dfs_limit=80
0.24046 sec.
dfs_limit=82
1.91567 sec.
dfs_limit=84
15.4637 sec.
dfs_limit=86
145.996 sec.
dfs_limit=88
1322.17 sec.
dfs_limit=90
11033.8 sec.
dfs_limit=92
*/
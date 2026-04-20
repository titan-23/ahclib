#pragma GCC target("avx2")
#pragma GCC optimize("O3")
#pragma GCC optimize("unroll-loops")

#include <bits/stdc++.h>
#include <ext/pb_ds/assoc_container.hpp>
#include <ext/pb_ds/hash_policy.hpp>
#include "titan_cpplib/others/print.cpp"
#include "titan_cpplib/ahc/state_pool.cpp"
#include "titan_cpplib/ahc/timer.cpp"
#include "titan_cpplib/algorithm/random.cpp"
#include "titan_cpplib/others/print.cpp"
#include "titan_cpplib/ahc/beam_search/beam_search.cpp"

using namespace std;

#define rep(i, n) for (int i = 0; i < (n); ++i)
template<typename T> T abs(const T a, const T b) { return a > b ? a-b : b-a; }

int N;
vector<vector<int>> A;

void input() {
    cin >> N;
    A.resize(N, vector<int>(N));
    rep(i, N) rep(j, N) {
        cin >> A[i][j];
    }
}

//! 木上のビームサーチライブラリ
namespace beam_search {

using ScoreType = int;
using HashType = unsigned long long;
const ScoreType INF = 1e9;
titan23::Random brnd;
HashType zhs[10][10][101]; // zhs[i][j][k]:=(i,j)にkがあるときのハッシュ
int revB[101];
HashType GOAL_HASH;

void beam_init() {
    rep(i, N) rep(j, N) rep(k, N*N+1) {
        zhs[i][j][k] = brnd.rand_u64();
    }
    rep(v, N*N) {
        revB[v] = ((v-1)%N)*N + ((v-1)/N);
    }
    revB[0] = 0;
}

// メモリ量は少ない方がよく、score,hash のメモは無くしたい
struct Action {
    char d;
    ScoreType pre_score, nxt_score;
    HashType pre_hash, nxt_hash;
    int pre_inv_ud, nxt_inv_ud;
    int pre_inv_lr, nxt_inv_lr;

    Action() {}
    Action(char d) : d(d), pre_score(INF), nxt_score(INF), pre_hash(0), nxt_hash(0) {}
    friend ostream& operator<<(ostream& os, const Action &action) {
        os << action.d;
        return os;
    }

    string to_string() const {
        return string(1, d);
    }
};

class State {
private:
    ScoreType score;
    HashType hash;

    vector<vector<int>> F;
    int y, x;
    int inv_ud, inv_lr;

    // (i, j) に v があるときのスコア
    int calc_pos(const int i, const int j, const int v) const {
        if (v == 0) return 0;
        int s = abs(i-((v-1)/N)) + abs(j-((v-1)%N));
        return s;
    }

    int get_inversion_ud() const {
        int cnt = 0;
        rep(i, N * N) {
            int y1 = i / N;
            int x1 = i % N;
            if (F[y1][x1] == 0) continue;
            for (int j = i + 1; j < N * N; ++j) {
                int y2 = j / N;
                int x2 = j % N;
                if (F[y2][x2] == 0) continue;
                if (F[y1][x1] > F[y2][x2]) {
                    ++cnt;
                }
            }
        }
        return cnt;
    }

    int get_inversion_lr() const {
        int cnt = 0;
        rep(i, N * N) {
            int y1 = i % N;
            int x1 = i / N;
            if (F[y1][x1] == 0) continue;
            for (int j = i + 1; j < N * N; ++j) {
                int y2 = j % N;
                int x2 = j / N;
                if (F[y2][x2] == 0) continue;
                if (revB[F[y1][x1]] > revB[F[y2][x2]]) {
                    ++cnt;
                }
            }
        }
        return cnt;
    }

public:
    void init() {
        this->score = 0;
        this->hash = 0;

        F = A;
        rep(i, N) rep(j, N) {
            if (F[i][j] == 0) {
                y = i; x = j;
            }
            score += calc_pos(i, j, F[i][j]);
            hash ^= zhs[i][j][F[i][j]];
        }

        GOAL_HASH = 0;
        rep(i, N) rep(j, N) {
            if (i == N-1 && j == N-1) {
                GOAL_HASH ^= zhs[i][j][0];
            } else {
                GOAL_HASH ^= zhs[i][j][i*N+j+1];
            }
        }

        inv_ud = get_inversion_ud();
        inv_lr = get_inversion_lr();
        int inv_dist = inv_ud/(N-1)+inv_ud%(N-1) + inv_lr/(N-1)+inv_lr%(N-1);
        score += inv_dist;
    }

    //! ロールバックに必要な情報はすべてactionにメモしておく
    //! threshold以上であれば計算しなくてよい
    //! INFを返すと無条件で採用しない
    tuple<ScoreType, HashType, bool> try_op(Action &action, const ScoreType threshold) const {
        action.pre_score = score;
        action.pre_hash = hash;
        action.pre_inv_ud = inv_ud;
        action.pre_inv_lr = inv_lr;

        int ny = y, nx = x;
        if (action.d == 'D') ++ny;
        if (action.d == 'U') --ny;
        if (action.d == 'R') ++nx;
        if (action.d == 'L') --nx;

        ScoreType nxt_score = score;
        HashType nxt_hash = hash;
        int nxt_inv_ud = inv_ud;
        int nxt_inv_lr = inv_lr;

        int pre_inv_dist = inv_ud/(N-1)+inv_ud%(N-1)+inv_lr/(N-1)+inv_lr%(N-1);
        nxt_score -= pre_inv_dist;
        nxt_score -= calc_pos(y, x, F[y][x]);
        nxt_score -= calc_pos(ny, nx, F[ny][nx]);

        nxt_score += calc_pos(y, x, F[ny][nx]);
        nxt_score += calc_pos(ny, nx, F[y][x]);

        if (nxt_score >= threshold) {
            return {INF, 0, 0};
        }

        nxt_hash ^= zhs[y][x][F[y][x]];
        nxt_hash ^= zhs[y][x][F[ny][nx]];
        nxt_hash ^= zhs[ny][nx][F[ny][nx]];
        nxt_hash ^= zhs[ny][nx][F[y][x]];

        if (action.d == 'D') {
            int fn = F[ny][nx];
            for (int ind = y * N + x + 1; ind < ny * N + nx; ++ind) {
                if (F[ind / N][ind % N] > fn) --nxt_inv_ud;
                else ++nxt_inv_ud;
            }
        } else if (action.d == 'R') {
            int fn = revB[F[ny][nx]];
            for (int ind = x * N + y + 1; ind < nx * N + ny; ++ind) {
                if (revB[F[ind % N][ind / N]] > fn) --nxt_inv_lr;
                else ++nxt_inv_lr;
            }
        } else if (action.d == 'U') {
            int fn = F[ny][nx];
            for (int ind = ny * N + nx + 1; ind < y * N + x; ++ind) {
                if (F[ind / N][ind % N] < fn) --nxt_inv_ud;
                else ++nxt_inv_ud;
            }
        } else if (action.d == 'L') {
            int fn = revB[F[ny][nx]];
            for (int ind = nx * N + ny + 1; ind < x * N + y; ++ind) {
                if (revB[F[ind % N][ind / N]] < fn) --nxt_inv_lr;
                else ++nxt_inv_lr;
            }
        }
        int nxt_inv_dist = nxt_inv_ud/(N-1) + nxt_inv_ud%(N-1) + nxt_inv_lr/(N-1) + nxt_inv_lr%(N-1);
        nxt_score += nxt_inv_dist;

        action.nxt_score = nxt_score;
        action.nxt_hash = nxt_hash;
        action.nxt_inv_ud = nxt_inv_ud;
        action.nxt_inv_lr = nxt_inv_lr;

        return {nxt_score, nxt_hash, nxt_hash == GOAL_HASH};
    }

    void apply_op(const Action &action) {
        int py = y, px = x;
        if (action.d == 'D') ++y;
        if (action.d == 'U') --y;
        if (action.d == 'R') ++x;
        if (action.d == 'L') --x;
        swap(F[y][x], F[py][px]);

        inv_lr = action.nxt_inv_lr;
        inv_ud = action.nxt_inv_ud;
        score = action.nxt_score;
        hash = action.nxt_hash;
    }

    void rollback(const Action &action) {
        int py = y, px = x;
        if (action.d == 'D') --y;
        if (action.d == 'U') ++y;
        if (action.d == 'R') --x;
        if (action.d == 'L') ++x;
        swap(F[y][x], F[py][px]);

        inv_lr = action.pre_inv_lr;
        inv_ud = action.pre_inv_ud;
        score = action.pre_score;
        hash = action.pre_hash;
    }

    //! 現状態から遷移可能な `Action` の `vector` を `actions` に入れる
    void get_actions(vector<Action> &actions, const int turn, const Action &last_action, const ScoreType threshold) const {
        auto rev = [&] () -> char {
            if (turn == 0) return 'Z';
            if (last_action.d == 'U') return 'D';
            if (last_action.d == 'D') return 'U';
            if (last_action.d == 'L') return 'R';
            if (last_action.d == 'R') return 'L';
            assert(false);
        };
        const string s = "UDLR";
        for (char c : s) {
            if (c == rev()) continue;
            int ny = y, nx = x;
            if (c == 'D') ++ny;
            if (c == 'U') --ny;
            if (c == 'R') ++nx;
            if (c == 'L') --nx;
            if (0 <= ny && ny < N && 0 <= nx && nx < N) {
                actions.push_back({c});
            }
        }
    }

    void print() const {
    }

    string get_state_info() const {
        return "{}";
    }
};


flying_squirrel::BeamParam gen_param(int max_turn, int beam_width) {
    return {max_turn, beam_width, -1};
}

flying_squirrel::BeamParam gen_param(int max_turn, int beam_width, double time_limit, bool is_adjusting) {
    return {max_turn, beam_width, time_limit, is_adjusting};
}

vector<Action> search(flying_squirrel::BeamParam &param, const bool verbose=false, const string& history_file = "") {
    flying_squirrel::BeamSearchWithTree<ScoreType, HashType, Action, State, INF, true> bs;
    return bs.search(param, verbose, history_file);
}
} // namespace beam_search


void solve() {
    beam_search::beam_init();
    auto param = beam_search::gen_param(1500, 1e1);
    auto ans = beam_search::search(param, true, "history.json");
    cerr << ans.size() << endl;
    for (auto action : ans) {
        cout << action;
    }
    cout << "\n";
}

int main() {
    input();
    solve();
    return 0;
}

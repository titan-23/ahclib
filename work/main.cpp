#pragma GCC target("avx2")
#pragma GCC optimize("O3")
#pragma GCC optimize("unroll-loops")
#include <bits/stdc++.h>
using namespace std;
using ll = long long;
#define rep(i, n) for (int i = 0; i < (int)(n); ++i)
template <class T, class U> T min(const T &t, const U &u) { return t < u ? t : u; }
template <class T, class U> T max(const T &t, const U &u) { return t < u ? u : t; }

#include "titan_cpplib/ahc/timer.cpp"
#include "titan_cpplib/algorithm/random.cpp"
#include "titan_cpplib/others/print.cpp"
// #include "titan_cpplib/ahc/beam_search/beam_search_turn.cpp"
#include "titan_cpplib/ahc/beam_search/gemini.cpp"

constexpr const int N = 10;
constexpr const int MAX_S = 15;
constexpr const int MAX_T = 20;
int R;
vector<vector<int>> Y;

void input() {
    cin >> R;
    Y.resize(R, vector<int>(N));
    rep(i, R) rep(j, N) cin >> Y[i][j];
}

namespace beam_search {

using ScoreType = long long;
using HashType = unsigned long long;
const ScoreType INF = 1e18;
titan23::Random brnd;

// zhs_s[v][i][j]:=値vが位置(i,j)にあるハッシュ
HashType zhs_s[N*N][N][MAX_S];
HashType zhs_t[N*N][N][MAX_T];
HashType hash_AC;

void beam_init() {
    rep(i, N*N) rep(j, N) rep(k, MAX_S) zhs_s[i][j][k] = brnd.rand_u64();
    rep(i, N*N) rep(j, N) rep(k, MAX_T) zhs_t[i][j][k] = brnd.rand_u64();
    hash_AC = 0;
    rep(i, N*N) {
        hash_AC ^= zhs_s[i][i/10][i%10];
    }
}

struct Action {
    ScoreType pre_score, nxt_score;
    HashType pre_hash, nxt_hash;
    int target_turn;
    int pre_turn, pre_s, pre_t;
    int nxt_turn, nxt_s, nxt_t;
    int si, ti;
    int scnt, tcnt;

    Action() : pre_score(INF), nxt_score(INF), pre_hash(0), nxt_hash(0), pre_turn(0), target_turn(-1) {}
    Action(int si, int ti, int scnt, int tcnt) : si(si), ti(ti), scnt(scnt), tcnt(tcnt) {}
    friend ostream& operator<<(ostream& os, const Action &action) {
        return os;
    }

    string to_string() const {
        return "";
    }
};

struct SArray {
    int sz;
    int data[MAX_S];

    SArray() : sz(0) {}

    SArray(const SArray& other) : sz(other.sz) {
        for (int i = 0; i < sz; ++i) data[i] = other.data[i];
    }
    SArray& operator=(const SArray& other) {
        if (this != &other) {
            sz = other.sz;
            for (int i = 0; i < sz; ++i) data[i] = other.data[i];
        }
        return *this;
    }

    void clear() { sz = 0; }
    void push_back(int v) { data[sz++] = v; }
    void pop_back() { --sz; }
    int back() const { return data[sz - 1]; }
    int size() const { return sz; }
    bool empty() const { return sz == 0; }
    int operator[](int i) const { return data[i]; }
};

struct TArray {
    int head;
    int data[MAX_T];

    TArray() : head(MAX_T) {}

    TArray(const TArray& other) : head(other.head) {
        for (int i = head; i < MAX_T; ++i) data[i] = other.data[i];
    }
    TArray& operator=(const TArray& other) {
        if (this != &other) {
            head = other.head;
            for (int i = head; i < MAX_T; ++i) data[i] = other.data[i];
        }
        return *this;
    }

    void clear() { head = MAX_T; }
    void push_front(int v) { data[--head] = v; }
    void pop_front() { ++head; }
    int front() const { return data[head]; }
    int size() const { return MAX_T - head; }
    bool empty() const { return head == MAX_T; }
    int operator[](int i) const { return data[head + i]; }
};

class State {
private:
    ScoreType score;
    HashType hash;
    int turn;
    int s, t;
    array<SArray, N> S;
    array<TArray, N> T;

public:
    void init() {
        turn = 0;
        s = 0;
        t = 0;
        rep(i, N) {
            S[i].clear();
            T[i].clear();
        }
        rep(i, N) rep(j, MAX_S) {
            if (j < N) S[i].push_back(Y[i][j]);
        }
        score = 0;
        rep(i, N) score += calc_score_S(i, S[i]);
        hash = 0;
        rep(i, N) hash ^= calc_hash_S(i, S[i]);
        rep(i, N) hash ^= calc_hash_T(i, T[i]);
    }

    bool is_consecutive(int x, int y) const {
        if (x % 10 == 9) return false;
        if (y != x+1) return false;
        return true;
    }

    HashType calc_hash_S(int c, const SArray &q) const {
        HashType h = 0;
        rep(k, q.size()) h ^= zhs_s[q[k]][c][k];
        return h;
    }

    HashType calc_hash_T(int c, const TArray &q) const {
        HashType h = 0;
        rep(k, q.size()) h ^= zhs_t[q[k]][c][k];
        return h;
    }

    ScoreType calc_score_S(int c, const SArray &q) const {
        ScoreType s = 0;
        rep(i, q.size()) {
            if (i == 0) {
                if (q[i] == c*10) s -= 100;
            } else {
                if (is_consecutive(q[i-1], q[i])) s -= 100;
            }
            s += abs(c - q[i]/10);
        }
        return s;
    }

    ScoreType calc_score_T(int c, const TArray &q) const {
        ScoreType s = 0;
        rep(i, q.size()) {
            if (i && is_consecutive(q[i-1], q[i])) s -= 100;
            s += abs(c - q[i]/10);
        }
        return s;
    }

    ScoreType pair_score(int i, const SArray &sq, int j, const TArray &tq) const {
        if (sq.empty() || tq.empty()) return 0;
        if (is_consecutive(sq.back(), tq.front())) return -50 + abs(i-j)*abs(i-j);
        return 0;
    }

    tuple<ScoreType, HashType, bool> try_op(Action &action, const vector<ScoreType>& thresholds) const {
        action.pre_score = score;
        action.pre_hash = hash;
        action.pre_turn = turn;
        ScoreType nxt_score = score;
        HashType nxt_hash = hash;

        action.pre_turn = turn;
        action.pre_s = s;
        action.pre_t = t;
        int i = action.si;
        int j = action.ti;
        if (i == -1 || j == -1) {
            action.nxt_turn = turn + 1;
            action.nxt_s = 0;
            action.nxt_t = 0;
            action.target_turn = (turn+1)*N*N;
            action.nxt_score = nxt_score;
            action.nxt_hash = nxt_hash;
            return {nxt_score, nxt_hash, hash == hash_AC};
        }

        action.nxt_turn = turn;
        action.nxt_s = i + 1;
        action.nxt_t = j + 1;
        if (action.nxt_s == N || action.nxt_t == N) {
            action.nxt_turn = turn + 1;
            action.nxt_s = 0;
            action.nxt_t = 0;
        }
        action.target_turn = (action.nxt_turn)*N*N + (action.nxt_s)*N + (action.nxt_t);
        if (nxt_score - 100*2 >= thresholds[action.target_turn]) return {INF, 0, 0};

        SArray ns = S[i];
        TArray nt = T[j];
        if (action.scnt != -1) {
            rep(_, action.scnt) {
                int v = ns.back();
                ns.pop_back();
                nt.push_front(v);
            }
        }
        if (action.tcnt != -1) {
            rep(_, action.tcnt) {
                int v = nt.front();
                nt.pop_front();
                ns.push_back(v);
            }
        }

        nxt_score -= calc_score_S(i, S[i]) + calc_score_T(j, T[j]);
        nxt_score += calc_score_S(i, ns) + calc_score_T(j, nt);
        rep(tc, N) {
            if (tc == j) continue;
            nxt_score -= pair_score(i, S[i], tc, T[tc]);
            nxt_score += pair_score(i, ns, tc, T[tc]);
        }
        rep(sc, N) {
            if (sc == i) continue;
            nxt_score -= pair_score(sc, S[sc], j, T[j]);
            nxt_score += pair_score(sc, S[sc], j, nt);
        }
        nxt_score -= pair_score(i, S[i], j, T[j]);
        nxt_score += pair_score(i, ns, j, nt);
        if (nxt_score >= thresholds[action.target_turn]) return {INF, 0, 0};

        nxt_hash ^= calc_hash_S(i, S[i]) ^ calc_hash_T(j, T[j]);
        nxt_hash ^= calc_hash_S(i, ns) ^ calc_hash_T(j, nt);

        action.nxt_score = nxt_score;
        action.nxt_hash = nxt_hash;
        return {nxt_score, nxt_hash, nxt_hash == hash_AC};
    }

    void apply_op(const Action &action) {
        int i = action.si;
        int j = action.ti;
        if (action.si != -1 && action.ti != -1) {
            if (action.scnt != -1) {
                rep(_, action.scnt) {
                    int v = S[i].back();
                    S[i].pop_back();
                    T[j].push_front(v);
                }
            }
            if (action.tcnt != -1) {
                rep(_, action.tcnt) {
                    int v = T[j].front();
                    T[j].pop_front();
                    S[i].push_back(v);
                }
            }
        }

        score = action.nxt_score;
        hash = action.nxt_hash;
        turn = action.nxt_turn;
        s = action.nxt_s;
        t = action.nxt_t;
    }

    void rollback(const Action &action) {
        int i = action.si;
        int j = action.ti;
        if (action.si != -1 && action.ti != -1) {
            if (action.scnt != -1) {
                rep(_, action.scnt) {
                    int v = T[j].front();
                    T[j].pop_front();
                    S[i].push_back(v);
                }
            }
            if (action.tcnt != -1) {
                rep(_, action.tcnt) {
                    int v = S[i].back();
                    S[i].pop_back();
                    T[j].push_front(v);
                }
            }
        }
        score = action.pre_score;
        hash = action.pre_hash;
        turn = action.pre_turn;
        s = action.pre_s;
        t = action.pre_t;
    }

    void get_actions(vector<Action> &actions, const Action &last_action, const vector<ScoreType> &thresholds) const {
        for (int i = s; i < N; ++i) {
            bool done = true;
            if (S[i].size() != N) done = false;
            int done_cnt = 0;
            if (done) {
                rep(j, N) {
                    if (S[i][j] != i*N+j) {
                        done = false;
                        break;
                    }
                    done_cnt++;
                }
            }
            if (done) continue;

            for (int j = t; j < N; ++j) {
                const int n = S[i].size();
                const int m = T[j].size();
                for (int p = 1; p <= n; ++p) {
                    if (m+p > MAX_T) break;
                    if (p < n && is_consecutive(S[i][n-p-1], S[i][n-p])) continue;
                    if (n-p < done_cnt) break;
                    if (n > 0 && m > 0 && is_consecutive(S[i].back(), T[j].front())) {
                        actions.push_back({i, j, p, -1});
                        continue;
                    }
                    if (actions.size() > 10 && brnd.randint(100) < 90) continue;
                    actions.push_back({i, j, p, -1});
                }

                for (int q = 1; q <= m; ++q) {
                    if (n+q > MAX_S) break;
                    if (q < m && is_consecutive(T[j][q-1], T[j][q])) continue;
                    if (n > 0 && m > 0 && is_consecutive(S[i].back(), T[j].front())) {
                        actions.push_back({i, j, -1, q});
                        continue;
                    }
                    if (actions.size() > 10 && brnd.randint(100) < 80) continue;
                    actions.push_back({i, j, -1, q});
                }
            }
        }
        actions.push_back({-1, -1, -1, -1});
    }

    void print() const {}

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

vector<Action> search(flying_squirrel::BeamParam &param, const bool verbose=false) {
    flying_squirrel::BeamSearchWithTree<ScoreType, HashType, Action, State, INF, false> bs;
    return bs.search(param, verbose, "history.json");
}
} // namespace beam_search

struct S {
    int type, i, j, k;
};

void solve() {
    beam_search::beam_init();
    auto param = beam_search::gen_param(1e4, 100);
    auto result = beam_search::search(param, true);
    cerr << "resulit.size()=" << result.size() << endl;
    vector<vector<S>> ans;
    int pre_turn = -1;
    for (auto &res : result) {
        if (res.pre_turn != pre_turn) {
            ans.push_back({});
        }
        pre_turn = res.pre_turn;
        if (res.si != -1 && res.ti != -1) {
            int type = res.scnt == -1 ? 1 : 0;
            int k = res.scnt == -1 ? res.tcnt : res.scnt;
            ans.back().push_back({type, res.si, res.ti, k});
        }
    }
    vector<vector<S>> final_ans;
    for (auto &turn_actions : ans) {
        if (!turn_actions.empty()) {
            final_ans.push_back(turn_actions);
        }
    }
    cout << final_ans.size() << "\n";
    for (auto &res : final_ans) {
        cout << res.size() << "\n";
        for (auto &s : res) {
            cout << s.type << " " << s.i << " " << s.j << " " << s.k << "\n";
        }
    }

    cerr << "Score = " << final_ans.size() << endl;
}

int main(int argc, char* argv[]) {
    ios::sync_with_stdio(false);
    cin.tie(0);
    cout << fixed << setprecision(3);
    cerr << fixed << setprecision(3);

    input();
    solve();

    return 0;
}

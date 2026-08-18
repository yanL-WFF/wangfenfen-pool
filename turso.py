"""Turso (libSQL) HTTP 客户端 —— 免依赖，让后端可以零成本用上持久化的云端 SQLite。

只需设置环境变量：
  TURSO_URL    形如 https://<db>.turso.io
  TURSO_TOKEN  数据库的访问令牌

API 与 sqlite3.Connection 保持一致：execute(sql, args) → cursor，支持 fetchone/fetchall，
行支持 r['col'] 和 r[i] 两种访问方式（类似 sqlite3.Row）。
"""
import json, urllib.request, urllib.error


class TursoRow(dict):
    """同时支持按下标和按列名访问的行对象。"""

    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._vals = list(values)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self._vals[k]
        return dict.__getitem__(self, k)

    def keys(self):
        return dict.keys(self)


class TursoCursor:
    def __init__(self, cols, rows, lastrowid=None, rowcount=0):
        self.cols = cols
        self._rows = [TursoRow(cols, r) for r in rows]
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class TursoDB:
    def __init__(self, url, token):
        self.url = url.rstrip('/')
        self.token = token

    @staticmethod
    def _arg(v):
        if v is None:
            return {"type": "null"}
        if isinstance(v, bool):
            return {"type": "integer", "value": int(v)}
        if isinstance(v, int):
            return {"type": "integer", "value": v}
        if isinstance(v, float):
            return {"type": "float", "value": v}
        return {"type": "text", "value": str(v)}

    def execute(self, sql, args=()):
        body = {
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": [self._arg(a) for a in args]}}
            ]
        }
        req = urllib.request.Request(
            self.url + "/v2/pipeline",
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())

        results = data.get("results") or []
        if not results:
            return TursoCursor([], [], None, 0)
        r0 = results[0]
        if r0.get("type") != "ok":
            raise RuntimeError("turso error: " + json.dumps(r0, ensure_ascii=False)[:200])
        inner = r0.get("response") or {}
        if inner.get("type") != "result":
            return TursoCursor([], [], None, 0)
        result = inner.get("result") or {}
        cols = result.get("cols") or []
        rows_raw = result.get("rows") or []
        norm = []
        for row in rows_raw:
            nr = []
            for cell in row:
                if isinstance(cell, dict) and "value" in cell:
                    nr.append(cell["value"])
                else:
                    nr.append(cell)
            norm.append(nr)
        lastrowid = result.get("last_insert_rowid") or None
        rowcount = result.get("affected_row_count", 0) or 0
        return TursoCursor(cols, norm, lastrowid, rowcount)

    # 每个 execute 自动提交，无需 commit
    def commit(self):
        pass

    def close(self):
        pass

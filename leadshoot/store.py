"""SQLite store.

Two ownership zones, never mixed:
  - engine-owned tables (businesses, runs, areas) are upserted by every run
  - user-owned tables (lead_status, icp, settings) are NEVER touched by ingest
Views join the two at query time.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = "leadshoot.db"

STAGES = ("new", "contacted", "interested", "won", "lost", "hidden")

# Well-known signal keys affect qualification or public context. Any other
# key is still stored and carried along (extensible).
K_RATING = "reviews.rating"
K_REVIEW_COUNT = "reviews.count"
K_FOLLOWERS = "social.followers"
K_LAST_POST_DAYS = "social.last_post_days"
K_SOCIAL_PROFILE = "social.profile"              # official-site profile links
K_WEBSITE_URL = "website.official_url"            # researcher-confirmed site
K_FOUNDED_YEAR = "business.founded_year"
K_DOMAIN_YEAR = "domain.registered_year"   # RDAP: maturity lower bound
K_BUILDER = "site.builder"                 # detected by the live check
KNOWN_SIGNAL_KEYS = (K_RATING, K_REVIEW_COUNT, K_FOLLOWERS,
                     K_LAST_POST_DAYS, K_SOCIAL_PROFILE, K_WEBSITE_URL,
                     K_FOUNDED_YEAR, K_DOMAIN_YEAR)

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  category      TEXT,
  osm_tags      TEXT DEFAULT '',
  phone         TEXT,
  email         TEXT,
  address       TEXT,
  lat           REAL,
  lon           REAL,
  osm_website   TEXT,
  area          TEXT,
  site_status   TEXT,
  http_code     INTEGER,
  has_ssl       INTEGER,
  is_mobile     INTEGER,
  has_booking   INTEGER,
  gap_flags     TEXT DEFAULT '',
  confidence    TEXT DEFAULT '',
  score         INTEGER DEFAULT 0,
  first_seen    TEXT,
  last_seen     TEXT,
  checked_at    TEXT,
  search_id     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_biz_filter ON businesses(category, score DESC);
CREATE INDEX IF NOT EXISTS idx_biz_area ON businesses(area);

CREATE TABLE IF NOT EXISTS runs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  icp_name    TEXT,
  area        TEXT,
  started_at  TEXT,
  finished_at TEXT,
  found       INTEGER DEFAULT 0,
  checked     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS areas (
  name        TEXT PRIMARY KEY,
  south REAL, west REAL, north REAL, east REAL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS signals (
  business_id TEXT NOT NULL,
  key         TEXT NOT NULL,
  source      TEXT NOT NULL,
  value       REAL,
  value_text  TEXT,
  url         TEXT,
  note        TEXT DEFAULT '',
  observed_at TEXT,
  PRIMARY KEY (business_id, key, source)
);

CREATE TABLE IF NOT EXISTS lead_status (
  business_id TEXT PRIMARY KEY,
  stage       TEXT DEFAULT 'new',
  note        TEXT DEFAULT '',
  updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS icp (
  name       TEXT PRIMARY KEY,
  definition TEXT NOT NULL,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or os.environ.get("LEADSHOOT_DB", DEFAULT_DB))
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was created. Safe to re-run.

        Indexes on migrated columns are created here (not in SCHEMA) so they
        never run before the column exists on an older database.
        """
        cols = {r["name"] for r in
                self.conn.execute("PRAGMA table_info(businesses)")}
        if "search_id" not in cols:
            self.conn.execute(
                "ALTER TABLE businesses ADD COLUMN search_id INTEGER")
        if "provider" not in cols:
            self.conn.execute(
                "ALTER TABLE businesses ADD COLUMN provider TEXT DEFAULT 'osm'")
        if "site_outdated" not in cols:
            self.conn.execute(
                "ALTER TABLE businesses ADD COLUMN site_outdated INTEGER")
            self.conn.execute(
                "ALTER TABLE businesses ADD COLUMN site_slow INTEGER")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_biz_search "
            "ON businesses(search_id)")
        # v0.2: review_signals generalized into signals(key,...)
        legacy = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='review_signals'").fetchone()
        if legacy:
            self.conn.execute(f"""
                INSERT OR IGNORE INTO signals
                  (business_id, key, source, value, url, note, observed_at)
                SELECT business_id, '{K_RATING}', source, rating, url, note,
                       added_at
                FROM review_signals WHERE rating IS NOT NULL""")
            self.conn.execute(f"""
                INSERT OR IGNORE INTO signals
                  (business_id, key, source, value, url, note, observed_at)
                SELECT business_id, '{K_REVIEW_COUNT}', source, review_count,
                       url, note, added_at
                FROM review_signals WHERE review_count IS NOT NULL""")
            self.conn.execute("DROP TABLE review_signals")

    def close(self) -> None:
        self.conn.close()

    # ---------- engine-owned: businesses ----------

    def upsert_business(self, biz: dict, search_id: int | None = None,
                        provider: str = "osm") -> None:
        """Roster upsert. Refreshes identity fields only - never check results.

        A location is never duplicated (PK = source id). The search that finds
        it CLAIMS it: search_id moves to the newest search, so each search's
        result set is exactly what it found, without accumulation.
        """
        now = utcnow()
        corrected = self.conn.execute(
            "SELECT value_text FROM signals WHERE business_id=? AND key=? "
            "ORDER BY observed_at DESC LIMIT 1",
            (biz["id"], K_WEBSITE_URL),
        ).fetchone()
        if corrected and corrected["value_text"]:
            biz = {**biz, "osm_website": corrected["value_text"]}
        self.conn.execute(
            """
            INSERT INTO businesses
              (id, name, category, osm_tags, phone, email, address, lat, lon,
               osm_website, area, first_seen, last_seen, search_id, provider)
            VALUES (:id, :name, :category, :osm_tags, :phone, :email, :address,
                    :lat, :lon, :osm_website, :area, :now, :now, :search_id,
                    :provider)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, category=excluded.category,
              osm_tags=excluded.osm_tags, phone=excluded.phone,
              email=excluded.email, address=excluded.address,
              lat=excluded.lat, lon=excluded.lon,
              osm_website=excluded.osm_website, area=excluded.area,
              last_seen=excluded.last_seen,
              search_id=COALESCE(excluded.search_id, businesses.search_id),
              provider=excluded.provider
            """,
            {**biz, "now": now, "search_id": search_id, "provider": provider},
        )

    def save_check(
        self,
        business_id: str,
        site_status: str,
        http_code: int | None,
        has_ssl: int | None,
        is_mobile: int | None,
        has_booking: int | None,
        gap_flags: list[str],
        confidence: str,
        score: int,
        site_outdated: int | None = None,
        site_slow: int | None = None,
        checked_at: str | None = None,
    ) -> None:
        """Persist a check + private rank. checked_at defaults to now; updates
        from stored facts pass the original timestamp through unchanged."""
        self.conn.execute(
            """
            UPDATE businesses SET site_status=?, http_code=?, has_ssl=?,
              is_mobile=?, has_booking=?, gap_flags=?, confidence=?, score=?,
              site_outdated=?, site_slow=?, checked_at=?
            WHERE id=?
            """,
            (site_status, http_code, has_ssl, is_mobile, has_booking,
             ",".join(gap_flags), confidence, score, site_outdated, site_slow,
             checked_at or utcnow(), business_id),
        )

    def businesses_in_search(self, search_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM businesses WHERE search_id=?", (search_id,)
        ).fetchall()

    def candidates_for_check(self, search_id: int,
                             max_age_days: int = 30) -> list[sqlite3.Row]:
        """This search's roster, minus businesses checked recently enough."""
        cutoff = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=max_age_days)
        ).isoformat(timespec="seconds")
        return self.conn.execute(
            """
            SELECT * FROM businesses
            WHERE search_id=?
              AND (checked_at IS NULL OR checked_at < ?)
            """,
            (search_id, cutoff),
        ).fetchall()

    # ---------- signals (agent-contributed facts, generic) ----------

    def add_signal(self, business_id: str, key: str, source: str,
                   value: float | None = None, text: str | None = None,
                   url: str | None = None, note: str = "") -> bool:
        """Persist one observed signal. Any key is accepted (extensible);
        only KNOWN_SIGNAL_KEYS affect scoring."""
        exists = self.conn.execute(
            "SELECT 1 FROM businesses WHERE id=?", (business_id,)
        ).fetchone()
        if not exists:
            return False
        normalized_key = key.strip().lower()
        self.conn.execute(
            """
            INSERT INTO signals
              (business_id, key, source, value, value_text, url, note,
               observed_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(business_id, key, source) DO UPDATE SET
              value=excluded.value, value_text=excluded.value_text,
              url=excluded.url, note=excluded.note,
              observed_at=excluded.observed_at
            """,
            (business_id, normalized_key, source.strip().lower(),
             value, text, url, note, utcnow()),
        )
        if normalized_key == K_WEBSITE_URL:
            # `url` is provenance for most signals; only the explicit text
            # value is the corrected official destination.
            official = (text or "").strip()
            if official:
                self.conn.execute(
                    "UPDATE businesses SET osm_website=? WHERE id=?",
                    (official, business_id),
                )
        self.conn.commit()
        return True

    def signals_for(self, business_id: str, key_prefix: str | None = None
                    ) -> list[dict]:
        sql = "SELECT * FROM signals WHERE business_id=?"
        params: list = [business_id]
        if key_prefix:
            sql += " AND key LIKE ?"
            params.append(f"{key_prefix}%")
        sql += " ORDER BY key, source"
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def signal_summary(self, business_id: str) -> dict:
        """Fold raw signals into the qualification summary values.

        reviews_rating   count-weighted avg across sources (fallback: mean)
        reviews_count    total across sources
        social_followers total audience across platforms
        social_last_post_days  most recent activity seen on any platform
        founded_year     earliest credible founding evidence
        """
        rows = self.signals_for(business_id)
        by_key: dict[str, dict[str, float]] = {}
        sources_with_reviews: set[str] = set()
        builder = None
        social_profiles: list[str] = []
        official_website = None
        for r in rows:
            if r["key"] == K_BUILDER and r["value_text"]:
                builder = r["value_text"]
            if r["key"] == K_SOCIAL_PROFILE and r["value_text"]:
                try:
                    values = json.loads(r["value_text"])
                except (TypeError, ValueError):
                    values = [r["value_text"]]
                for value in values if isinstance(values, list) else [values]:
                    if value and str(value) not in social_profiles:
                        social_profiles.append(str(value))
            if r["key"] == K_WEBSITE_URL:
                official_website = r["value_text"]
            if r["value"] is None:
                continue
            by_key.setdefault(r["key"], {})[r["source"]] = r["value"]
            if r["key"] in (K_RATING, K_REVIEW_COUNT):
                sources_with_reviews.add(r["source"])

        ratings = by_key.get(K_RATING, {})
        counts = by_key.get(K_REVIEW_COUNT, {})
        rating = None
        if ratings:
            paired = [(v, counts.get(s)) for s, v in ratings.items()
                      if counts.get(s)]
            if paired:
                total_w = sum(c for _, c in paired)
                rating = round(sum(v * c for v, c in paired) / total_w, 2)
            else:
                rating = round(sum(ratings.values()) / len(ratings), 2)
        followers = by_key.get(K_FOLLOWERS, {})
        last_post = by_key.get(K_LAST_POST_DAYS, {})
        founded = by_key.get(K_FOUNDED_YEAR, {})
        domain = by_key.get(K_DOMAIN_YEAR, {})
        return {
            "reviews_rating": rating,
            "reviews_count": int(sum(counts.values())) if counts else None,
            "reviews_sources": ",".join(sorted(sources_with_reviews)) or None,
            "social_followers": int(sum(followers.values())) if followers else None,
            "social_last_post_days": int(min(last_post.values())) if last_post else None,
            "founded_year": int(min(founded.values())) if founded else None,
            "domain_registered_year": int(min(domain.values())) if domain else None,
            "builder": builder,
            "social_profiles": social_profiles,
            "official_website": official_website,
        }

    # -- compatibility wrappers (review-shaped API) --

    def add_review_signal(self, business_id: str, source: str,
                          rating: float | None = None,
                          review_count: int | None = None,
                          url: str | None = None, note: str = "") -> bool:
        ok = True
        wrote = False
        if rating is not None:
            ok &= self.add_signal(business_id, K_RATING, source,
                                  value=rating, url=url, note=note)
            wrote = True
        if review_count is not None:
            ok &= self.add_signal(business_id, K_REVIEW_COUNT, source,
                                  value=review_count, url=url, note=note)
            wrote = True
        if not wrote:  # signal with no numbers still records the attempt
            ok = self.add_signal(business_id, K_REVIEW_COUNT, source,
                                 value=0, url=url, note=note or "no data")
        return ok

    def review_signals_for(self, business_id: str) -> list[dict]:
        return self.signals_for(business_id, key_prefix="reviews.")

    def review_summary(self, business_id: str) -> tuple[float | None, int | None]:
        s = self.signal_summary(business_id)
        return (s["reviews_rating"], s["reviews_count"])

    def update_gaps_score(self, business_id: str, gap_flags: list[str],
                          confidence: str, score: int) -> None:
        """Recompute private order without touching check facts."""
        self.conn.execute(
            "UPDATE businesses SET gap_flags=?, confidence=?, score=? WHERE id=?",
            (",".join(gap_flags), confidence, score, business_id),
        )
        self.conn.commit()

    def get_business(self, business_id: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT b.*, COALESCE(s.stage,'new') AS stage,
                   COALESCE(s.note,'') AS note, r.icp_name AS icp_name
            FROM businesses b
            LEFT JOIN lead_status s ON s.business_id=b.id
            LEFT JOIN runs r ON r.id=b.search_id
            WHERE b.id=?
            """,
            (business_id,),
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["signals"] = self.signals_for(business_id)
        out.update(self.signal_summary(business_id))
        return out

    # ---------- joined queries ----------

    def leads(
        self,
        stage: str | None = None,
        gap: str | None = None,
        min_score: int = 0,
        limit: int = 50,
        area: str | None = None,
        categories: list[str] | None = None,
        fresh_only: bool = False,
        search_id: int | None = None,
    ) -> list[dict]:
        """Businesses joined with the user's pipeline.

        fresh_only=True is the `find` behaviour: exclude anything already
        worked (stage other than 'new') or hidden. search_id scopes to one
        search's result set (each search owns exactly what it found).
        """
        sql = """
          SELECT b.*, COALESCE(s.stage, 'new') AS stage,
                 COALESCE(s.note, '') AS note, s.updated_at AS stage_updated_at,
                 r.icp_name AS icp_name
          FROM businesses b
          LEFT JOIN lead_status s ON s.business_id = b.id
          LEFT JOIN runs r ON r.id = b.search_id
          WHERE b.score >= ?
        """
        params: list = [min_score]
        if fresh_only:
            sql += " AND (s.stage IS NULL OR s.stage = 'new')"
        if stage:
            sql += " AND COALESCE(s.stage,'new') = ?"
            params.append(stage)
        else:
            sql += " AND COALESCE(s.stage,'new') != 'hidden'"
        if gap:
            sql += " AND (',' || b.gap_flags || ',') LIKE ?"
            params.append(f"%,{gap},%")
        if area:
            sql += " AND b.area = ?"
            params.append(area)
        if categories:
            sql += f" AND b.category IN ({','.join('?' * len(categories))})"
            params.extend(categories)
        if search_id is not None:
            sql += " AND b.search_id = ?"
            params.append(search_id)
        sql += " ORDER BY b.score DESC, b.name LIMIT ?"
        params.append(limit)
        # only leads with recorded signals pay the per-row summary cost
        with_signals = {
            r["business_id"] for r in
            self.conn.execute("SELECT DISTINCT business_id FROM signals")
        }
        empty = {"reviews_rating": None, "reviews_count": None,
                 "reviews_sources": None, "social_followers": None,
                 "social_last_post_days": None, "founded_year": None,
                 "domain_registered_year": None, "builder": None,
                 "social_profiles": [], "official_website": None}
        out = []
        for r in self.conn.execute(sql, params).fetchall():
            d = dict(r)
            d.update(self.signal_summary(d["id"])
                     if d["id"] in with_signals else empty)
            out.append(d)
        return out

    # ---------- user-owned: pipeline ----------

    def mark(self, business_id: str, stage: str | None = None,
             note: str | None = None) -> bool:
        if stage is not None and stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        exists = self.conn.execute(
            "SELECT 1 FROM businesses WHERE id=?", (business_id,)
        ).fetchone()
        if not exists:
            return False
        cur = self.conn.execute(
            "SELECT stage, note FROM lead_status WHERE business_id=?",
            (business_id,),
        ).fetchone()
        new_stage = stage if stage is not None else (cur["stage"] if cur else "new")
        new_note = note if note is not None else (cur["note"] if cur else "")
        self.conn.execute(
            """
            INSERT INTO lead_status (business_id, stage, note, updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(business_id) DO UPDATE SET
              stage=excluded.stage, note=excluded.note, updated_at=excluded.updated_at
            """,
            (business_id, new_stage, new_note, utcnow()),
        )
        self.conn.commit()
        return True

    # ---------- user-owned: icp & settings ----------

    def save_icp(self, name: str, definition: dict) -> None:
        now = utcnow()
        self.conn.execute(
            """
            INSERT INTO icp (name, definition, created_at, updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
              definition=excluded.definition, updated_at=excluded.updated_at
            """,
            (name, json.dumps(definition), now, now),
        )
        self.conn.commit()

    def get_icp(self, name: str) -> dict | None:
        row = self.conn.execute(
            "SELECT definition FROM icp WHERE name=?", (name,)
        ).fetchone()
        if not row:
            return None
        definition = json.loads(row["definition"])
        definition.pop("min_score", None)  # legacy numeric public setting
        definition.setdefault("min_priority", "not_sure")
        return definition

    def list_icps(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT name, definition, updated_at FROM icp ORDER BY updated_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            definition = json.loads(r["definition"])
            definition.pop("min_score", None)
            definition.setdefault("min_priority", "not_sure")
            out.append({"name": r["name"], "updated_at": r["updated_at"],
                        **definition})
        return out

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ---------- areas & runs ----------

    def get_area(self, name: str) -> tuple[float, float, float, float] | None:
        row = self.conn.execute(
            "SELECT south,west,north,east FROM areas WHERE name=?", (name.lower(),)
        ).fetchone()
        return (row["south"], row["west"], row["north"], row["east"]) if row else None

    def save_area(self, name: str, bbox: tuple[float, float, float, float]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO areas (name,south,west,north,east,resolved_at) "
            "VALUES (?,?,?,?,?,?)",
            (name.lower(), *bbox, utcnow()),
        )
        self.conn.commit()

    def latest_search_id(self, icp_name: str) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM runs WHERE icp_name=? ORDER BY id DESC LIMIT 1",
            (icp_name,),
        ).fetchone()
        return row["id"] if row else None

    def start_run(self, icp_name: str, area: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (icp_name, area, started_at) VALUES (?,?,?)",
            (icp_name, area, utcnow()),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, found: int, checked: int) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, found=?, checked=? WHERE id=?",
            (utcnow(), found, checked, run_id),
        )
        self.conn.commit()

    def list_runs(self, limit: int = 50) -> list[dict]:
        """Search history, newest first - each run id is a search version."""
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_run_id(self) -> int | None:
        row = self.conn.execute("SELECT MAX(id) m FROM runs").fetchone()
        return row["m"]

    # ---------- status ----------

    def status(self) -> dict:
        c = self.conn
        biz = c.execute("SELECT COUNT(*) n FROM businesses").fetchone()["n"]
        checked = c.execute(
            "SELECT COUNT(*) n FROM businesses WHERE checked_at IS NOT NULL"
        ).fetchone()["n"]
        with_gaps = c.execute(
            "SELECT COUNT(*) n FROM businesses WHERE gap_flags != '' "
            "AND gap_flags IS NOT NULL"
        ).fetchone()["n"]
        stages = {
            r["stage"]: r["n"]
            for r in c.execute(
                "SELECT stage, COUNT(*) n FROM lead_status GROUP BY stage"
            ).fetchall()
        }
        icps = [r["name"] for r in c.execute("SELECT name FROM icp").fetchall()]
        last = c.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "db": self.path,
            "businesses": biz,
            "checked": checked,
            "with_gaps": with_gaps,
            "pipeline": stages,
            "icps": icps,
            "last_run": dict(last) if last else None,
        }

    def facets(self, search_id: int | None = None) -> dict:
        """Which gaps and stages ACTUALLY occur in the current scope, with
        counts. A UI builds its filters from this so it only ever offers a
        gap that would return something - derived from the data, never a
        hardcoded list. Scope to one search, or the whole DB (search_id=None)."""
        where = "WHERE search_id=?" if search_id is not None else ""
        args = (search_id,) if search_id is not None else ()
        gaps: dict[str, int] = {}
        for row in self.conn.execute(
                f"SELECT gap_flags FROM businesses {where}", args):
            for g in (row["gap_flags"] or "").split(","):
                if g:
                    gaps[g] = gaps.get(g, 0) + 1
        if search_id is not None:
            stage_rows = self.conn.execute(
                "SELECT ls.stage AS stage, COUNT(*) AS n FROM lead_status ls "
                "JOIN businesses b ON b.id = ls.business_id "
                "WHERE b.search_id=? GROUP BY ls.stage", (search_id,))
        else:
            stage_rows = self.conn.execute(
                "SELECT stage, COUNT(*) AS n FROM lead_status GROUP BY stage")
        stages = {r["stage"]: r["n"] for r in stage_rows}
        return {"gaps": gaps, "stages": stages}

    def change_token(self) -> str:
        """Cheap fingerprint of everything the UI renders. Any committed
        write - roster upsert, check persisted, run started/finished, signal
        added, stage changed - yields a new token, so a watcher can poll this
        instead of re-reading the world."""
        row = self.conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM businesses)                        AS b_n,
              (SELECT IFNULL(MAX(last_seen), '') FROM businesses)      AS b_seen,
              (SELECT IFNULL(MAX(checked_at), '') FROM businesses)     AS b_checked,
              (SELECT IFNULL(MAX(id), 0) FROM runs)                    AS r_max,
              (SELECT IFNULL(MAX(IFNULL(finished_at, '')), '')
                 FROM runs)                                            AS r_fin,
              (SELECT COUNT(*) FROM signals)                           AS s_n,
              (SELECT COUNT(*) || ':' || IFNULL(MAX(rowid), 0)
                 FROM lead_status)                                     AS ls
            """
        ).fetchone()
        return "|".join(str(v) for v in tuple(row))

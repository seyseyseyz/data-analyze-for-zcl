def create_note_metrics_view(con) -> None:
    note_columns = {
        row[1] for row in con.sql("PRAGMA table_info('notes')").fetchall()
    }
    impressions = "CAST(impressions AS DOUBLE)" if "impressions" in note_columns else "NULL"
    reads = "CAST(reads AS DOUBLE)" if "reads" in note_columns else "NULL"
    likes = "COALESCE(CAST(likes AS DOUBLE), 0)" if "likes" in note_columns else "0"
    collects = (
        "COALESCE(CAST(collects AS DOUBLE), 0)" if "collects" in note_columns else "0"
    )
    comments = (
        "COALESCE(CAST(comments AS DOUBLE), 0)" if "comments" in note_columns else "0"
    )
    shares = "COALESCE(CAST(shares AS DOUBLE), 0)" if "shares" in note_columns else "0"
    con.execute(
        f"""
        CREATE OR REPLACE VIEW note_metrics AS
        SELECT
          *,
          CASE WHEN {impressions} > 0 THEN {reads} * 1.0 / {impressions} END AS read_rate,
          CASE WHEN {reads} > 0 THEN {likes} * 1.0 / {reads} END AS like_rate,
          CASE WHEN {reads} > 0 THEN {collects} * 1.0 / {reads} END AS collect_rate,
          CASE WHEN {reads} > 0 THEN {comments} * 1.0 / {reads} END AS comment_rate,
          CASE
            WHEN {reads} > 0 THEN
              ({likes} + {collects} + {comments} + {shares}) * 1.0 / {reads}
          END AS engagement_rate
        FROM notes
        """
    )

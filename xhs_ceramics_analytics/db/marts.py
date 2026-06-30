def create_note_metrics_view(con) -> None:
    note_columns = {
        row[1] for row in con.sql("PRAGMA table_info('notes')").fetchall()
    }
    shares_expression = "COALESCE(shares, 0)" if "shares" in note_columns else "0"
    con.execute(
        f"""
        CREATE OR REPLACE VIEW note_metrics AS
        SELECT
          *,
          CASE WHEN impressions > 0 THEN reads * 1.0 / impressions END AS read_rate,
          CASE WHEN reads > 0 THEN likes * 1.0 / reads END AS like_rate,
          CASE WHEN reads > 0 THEN collects * 1.0 / reads END AS collect_rate,
          CASE WHEN reads > 0 THEN comments * 1.0 / reads END AS comment_rate,
          CASE
            WHEN reads > 0 THEN
              (likes + collects + comments + {shares_expression}) * 1.0 / reads
          END AS engagement_rate
        FROM notes
        """
    )

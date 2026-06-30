def create_note_metrics_view(con) -> None:
    con.execute(
        """
        CREATE OR REPLACE VIEW note_metrics AS
        SELECT
          *,
          CASE WHEN impressions > 0 THEN reads * 1.0 / impressions END AS read_rate,
          CASE WHEN reads > 0 THEN likes * 1.0 / reads END AS like_rate,
          CASE WHEN reads > 0 THEN collects * 1.0 / reads END AS collect_rate,
          CASE WHEN reads > 0 THEN comments * 1.0 / reads END AS comment_rate,
          CASE WHEN reads > 0 THEN (likes + collects + comments + COALESCE(shares, 0)) * 1.0 / reads END AS engagement_rate
        FROM notes
        """
    )

# comments

One row per comment when comment-level exports are available.

## Primary Key

(`note_id`, `comment_time`, `comment_text`) — or `comment_id` when available.

## Required Columns

| Column | Type | Description |
|--------|------|-------------|
| `note_id` | str | Note identifier |
| `comment_time` | datetime | Comment timestamp |
| `comment_text` | str | Comment text content |

## Optional Columns

| Column | Type | Description |
|--------|------|-------------|
| `comment_id` | str \| None | Unique comment identifier |
| `parent_comment_id` | str \| None | Parent comment ID for threaded replies |
| `comment_like_count` | int \| None | Number of likes on the comment |
| `author_id_hash` | str \| None | Hashed comment author identifier |
| `raw_file` | str \| None | Source raw file name/path for lineage |
| `raw_row_id` | str \| None | Source row identifier for lineage |

## Join Keys

- `note_id` references `notes.note_id`

## Chinese Aliases (from mapping.py FIELD_ALIASES)

No dedicated aliases for `comments` in FIELD_ALIASES (the table signature uses English column names: note_id, comment_time, comment_text).

## Sample Row

```json
{"note_id": "N001", "comment_time": "2025-01-16T14:00:00", "comment_text": "very beautiful cup", "comment_id": null, "parent_comment_id": null, "comment_like_count": 3, "author_id_hash": null}
```

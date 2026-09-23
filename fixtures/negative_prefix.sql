-- Both effects must disappear when the later catalog assertion aborts.
INSERT INTO rehearsal.items VALUES (99, 'rollback-only', 7);
CREATE TABLE rehearsal.rollback_probe (note text);

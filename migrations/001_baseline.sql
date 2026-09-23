-- Earlier migration: preserve these bytes; do not repair by editing this file.
CREATE SCHEMA rehearsal;
CREATE TABLE rehearsal.items (
    id integer PRIMARY KEY,
    label text NOT NULL,
    qty integer NOT NULL,
    CONSTRAINT items_qty_nonnegative CHECK (qty >= 0)
);
INSERT INTO rehearsal.items VALUES (1, 'pencil', 3), (2, 'notebook', 5);

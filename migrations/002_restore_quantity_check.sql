-- Forward-only correction, after the deliberate fixture drift.
-- This is not an idempotent migration and is not a production repair recipe.
ALTER TABLE rehearsal.items
    ADD CONSTRAINT items_qty_nonnegative CHECK (qty >= 0);

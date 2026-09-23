DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = 'rehearsal.items'::regclass
          AND conname = 'items_qty_nonnegative'
          AND contype = 'c' AND convalidated
          AND pg_catalog.pg_get_constraintdef(oid) = 'CHECK ((qty >= 0))'
    ) THEN
        RAISE EXCEPTION USING ERRCODE = 'P0001',
            MESSAGE = 'REHEARSAL_DRIFT: items_qty_nonnegative missing or changed';
    END IF;
END
$$;

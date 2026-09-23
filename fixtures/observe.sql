SELECT json_build_object(
    'rows', (SELECT json_agg(json_build_array(id, label, qty) ORDER BY id)
             FROM rehearsal.items),
    'constraints', (SELECT json_agg(json_build_array(conname, contype::text,
                       convalidated, pg_get_constraintdef(oid)) ORDER BY conname)
                    FROM pg_catalog.pg_constraint
                    WHERE conrelid = 'rehearsal.items'::regclass),
    'columns', (SELECT json_agg(json_build_array(attname, atttypid::regtype::text,
                       attnotnull) ORDER BY attnum)
                FROM pg_catalog.pg_attribute
                WHERE attrelid = 'rehearsal.items'::regclass AND attnum > 0 AND NOT attisdropped),
    'probe', to_regclass('rehearsal.rollback_probe')::text
);

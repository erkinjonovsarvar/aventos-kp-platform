-- 0003: import qilingan KP qatorining manbasi (fayl/varaq va qator raqami) — CLAUDE.md: har yozuv manbasi bilan.
ALTER TABLE quotation_line_custom
    ADD COLUMN source_document_id bigint REFERENCES source_document(id),
    ADD COLUMN source_row integer CHECK (source_row > 0),
    ADD CONSTRAINT quotation_line_custom_source_pair
        CHECK ((source_document_id IS NULL) = (source_row IS NULL));
CREATE INDEX ix_line_custom_source ON quotation_line_custom(source_document_id, source_row);

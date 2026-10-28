-- 0005: audit jurnali qo'shimcha jadvallarda ham (C002 tekshiruvida topilgan bo'shliq, 2026-10-15).
-- Ilova nomi, xodim (menejer) holati, loyiha, kategoriya, mahsulot va narx ro'yxati qatorlari o'zgarishlari ham yoziladi.
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation_annex    FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON employee           FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON project            FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON product_category   FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON product            FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON price_list_item    FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation_line_price_list FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON quotation_line_ahu_item   FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON invitation         FOR EACH ROW EXECUTE FUNCTION trg_audit();

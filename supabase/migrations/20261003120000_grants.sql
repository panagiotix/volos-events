-- Δικαιώματα πρόσβασης στους πίνακες (οι κανόνες RLS συνεχίζουν να ισχύουν από πάνω)
grant usage on schema public to anon, authenticated, service_role;

-- διαχειριστής (συνδεδεμένος): πλήρης πρόσβαση, περιορισμένη από το is_admin() των κανόνων
grant select, insert, update, delete on events, sources, submissions, reports to authenticated;

-- επισκέπτης: μόνο υποβολές, αναφορές και ανάγνωση δημοσιευμένων
grant insert on submissions, reports to anon;
grant select on events to anon;
grant select on public_events to anon, authenticated;

-- το workflow (κλειδί service_role): πλήρης πρόσβαση
grant all on events, sources, submissions, reports, admins to service_role;
grant select on public_events to service_role;

-- αριθμοί που δίνονται αυτόματα στις νέες γραμμές
grant usage, select on all sequences in schema public to anon, authenticated, service_role;

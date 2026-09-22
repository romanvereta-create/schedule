# TEMLI data map

This is a technical inventory for legal review. It is not a privacy policy.

| Category | Typical fields | Data subjects | Purpose | Current location |
| --- | --- | --- | --- | --- |
| Telegram identity | numeric ID, username, role/binding | teacher, student, parent | authentication, invitations, notifications | Russian storage JSON |
| Student profile | name/alias, contacts, birthday, notes, board link | student, parent | lesson management and communication | Russian storage JSON |
| Schedule | dates, times, attendance/status, group membership | teacher, student | calendar and reminders | Russian storage JSON |
| Financial records | lesson price, payment status, package allocation, reversals | teacher, student/customer | teacher accounting and receipts | Russian storage JSON/XLSX |
| Receipt settings | business identity, tax/bank details, logo/signature/QR | teacher/operator | receipt generation | Russian storage JSON/files |
| Generated files | receipts, exports, uploaded receipt assets | teacher, student/customer | reporting and delivery | Russian storage files |
| Personal bot credentials | encrypted token/webhook secret | teacher/operator | optional personal bot operation | Russian storage, encrypted |
| Operational metadata | release ID, health, backup age/count, generic errors | operator | reliability and incident response | application logs/status |
| Backups | copy of the categories above plus manifest | all applicable subjects | disaster recovery | Russian storage and candidate replica |

## Data flows

1. Telegram provides signed WebApp initialization data to the candidate.
2. The candidate validates it and resolves the tenant/role.
3. The candidate reads and writes tenant data through the authenticated Russian
   storage API.
4. Storage creates integrity-checked archives; the candidate downloads verified
   copies into its persistent replica directory.
5. Telegram may receive reminders, receipts, and exports initiated by an
   authorized teacher.

## Decisions required before promotion

- identify the legal operator/controller and publish its full contact details;
- define legal grounds and separate consent where required;
- define retention per category, including backups and deletion requests;
- decide rules for minors and parent/guardian contacts;
- document processors/hosting providers and cross-border transfers, if any;
- define the subject-request and incident-notification process;
- decide whether receipt/accounting features are informational records or part
  of a regulated fiscal/payment process, and describe them accurately.

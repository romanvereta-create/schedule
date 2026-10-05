# TEMLI data map

This is a technical inventory for legal review. It is not a privacy policy.

**Deployment evidence (2026-10-02):** application, Mini App, storage and local
backups run on Selectel VDS `temli-prod`, selected location Moscow `ru-2c`, IP
`135.106.173.105`. Provider evidence is still required for physical disks,
provider snapshots, logs and backups and for applicability of Selectel's 152-FZ
documents to the VDS product. `storage`, `backups` and `replica` are currently on
the same VDS; there is no independent offsite copy yet. Google Drive and the old
BotHost projects are not part of this contour.

| Category | Typical fields | Data subjects | Purpose | Current location |
| --- | --- | --- | --- | --- |
| Telegram identity | numeric ID, username, role/binding | teacher, student, parent | authentication, invitations, notifications | Selectel VDS JSON in Russia |
| Student profile | name/alias, Telegram identity, phone, parent name, notes, lesson link | student, parent | lesson management and communication | Selectel VDS JSON in Russia |
| Schedule | dates, times, attendance/status, group membership | teacher, student | calendar and reminders | Russian storage JSON |
| Financial records | lesson price, payment status, package allocation, reversals | teacher, student/customer | teacher accounting and receipts | Russian storage JSON/XLSX |
| Receipt settings | business identity, tax/bank details, logo/signature/QR | teacher/operator | receipt generation | Russian storage JSON/files |
| Generated files | receipts, exports, uploaded receipt assets | teacher, student/customer | reporting and delivery | Russian storage files |
| Personal bot credentials | encrypted token/webhook secret | teacher/operator | optional personal bot operation | Russian storage, encrypted |
| Operational metadata | release ID, health, backup age/count, generic errors | operator | reliability and incident response | application logs/status |
| Backups | copy of the categories above plus manifest | all applicable subjects | disaster recovery | Russian storage and candidate replica |

## Data flows

1. Telegram provides signed WebApp initialization data to `temli-prod`.
2. The application validates it and resolves the tenant/role.
3. The application reads and writes tenant data through a storage service on the
   private Docker network of the same Russian VDS.
4. Storage creates integrity-checked archives in `/var/lib/temli/backups`; a
   local replica exists in `/var/lib/temli/replica`. Both share the server's
   failure domain until a separate Russian offsite target is configured.
5. Telegram may receive minimized reminders through a teacher's branded bot.
   The Bot API TLS connection is transported through an Estonian proxy; the
   database, files and backups are not routed through it.

## Decisions required before promotion

- identify the legal operator/controller and publish its full contact details;
- define legal grounds and separate consent where required;
- apply `legal/retention-matrix.draft.md`, including backups and deletion requests;
- decide rules for minors and parent/guardian contacts;
- document processors/hosting providers and cross-border transfers, if any;
- define the subject-request and incident-notification process;
- decide whether receipt/accounting features are informational records or part
  of a regulated fiscal/payment process, and describe them accurately.

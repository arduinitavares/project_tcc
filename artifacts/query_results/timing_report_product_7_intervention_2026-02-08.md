============================================================================
 RELATÓRIO DE TEMPOS — INTERVENÇÃO (product_id = 7)
 DB: db/spec_authority_dev.db
 Extraído em: 2026-02-08
============================================================================

Evento                      | Tabela.campo                          | Timestamp completo
----------------------------|---------------------------------------|-------------------------------
Produto criado (T1)         | products.created_at                   | 2026-02-08 00:59:40.774781
Spec registrada (T2)        | spec_registry.created_at              | 2026-02-08 00:59:40.951723
Spec aprovada (T2)          | spec_registry.approved_at             | 2026-02-08 00:59:40.950060
Autoridade compilada (T3)   | compiled_spec_authority.compiled_at   | 2026-02-08 01:00:01.474190
Primeira story criada (T4)  | MIN(user_stories.created_at)          | 2026-02-08 01:02:34.115683
Última story criada (T4)    | MAX(user_stories.created_at)          | 2026-02-08 01:13:57.792859
Sprint plan saved (T5)      | workflow_events.timestamp             | 2026-02-08 01:16:53.961203

----------------------------------------------------------------------------
 DELTAS DERIVADOS (wall-clock, timestamps do DB)
----------------------------------------------------------------------------

Delta                                   | De → Até                        | Segundos  | mm:ss
----------------------------------------|---------------------------------|-----------|------
T1→T2  Visão → Spec                     | 00:59:40.77 → 00:59:40.95      |      0.18 | 00:00
T2→T3  Spec → Autoridade compilada      | 00:59:40.95 → 01:00:01.47      |     20.52 | 00:21
T3→T4  Autoridade → Primeira story      | 01:00:01.47 → 01:02:34.12      |    152.64 | 02:33
T4     Primeira → Última story (38 stories) | 01:02:34.12 → 01:13:57.79  |    683.68 | 11:24
T4→T5  Última story → Sprint plan saved | 01:13:57.79 → 01:16:53.96      |    176.17 | 02:56
T1→T5  Total (produto criado → sprint)  | 00:59:40.77 → 01:16:53.96      |   1033.19 | 17:13

----------------------------------------------------------------------------
 NOTAS
----------------------------------------------------------------------------
- duration_seconds do workflow_events: NULL (não preenchido pelo código)
- T1 e T2 são quase simultâneos porque visão+spec são carregados no mesmo
  fluxo de criação do produto (delta < 0.2s)
- Todos os tempos são da condição INTERVENÇÃO (plataforma com agentes)
- Tempos baseline (manual) NÃO estão no DB

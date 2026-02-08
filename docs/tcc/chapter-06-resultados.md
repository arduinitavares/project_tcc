# CAPÍTULO 6 — Resultados

Este capítulo apresenta os resultados obtidos na avaliação empírica exploratória do artefato. Os valores numéricos reportados são derivados de evidências extraídas do banco de dados e de artefatos de extração (CSV/JSON) gerados por script, conforme o protocolo definido no Capítulo 5. Quando um dado não está disponível no repositório (por exemplo, respostas de questionário NASA-TLX), isso é indicado explicitamente, evitando inferências não suportadas.

## 6.1 Caracterização da execução e do conjunto de evidências

Os resultados quantitativos deste capítulo são extraídos de uma base SQLite específica utilizada na avaliação, com metadados de extração registrados em artefato JSON.

**Fonte de verdade (evidência):**

- Base: `db/spec_authority_dev.db`
- Timestamp de extração: 2026-02-08T12:43:31Z
- Commit (hash curto): ab06268e1d06

**Produto avaliado (evidência):**

- `product_id = 7`
- Nome: *Review-First Human-in-the-Loop Extraction Pipeline*
- Especificação: 1 versão registrada e aprovada (`spec_version_id = 8`, status `approved`)

## 6.2 Resultados por dimensão de análise

### 6.2.1 Qualidade e completude mínima das histórias (validação determinística)

Esta dimensão reporta resultados de validação persistidos no banco por história. A evidência é composta por:

- campo `validation_evidence` (JSON) em `user_stories`, contendo resultado da validação e lista de falhas;
- campo `accepted_spec_version_id` em `user_stories`, preenchido quando a história passa na validação e é pinada à versão aprovada.

**Resumo (evidência):**

| Métrica | Valor | Interpretação |
|---|---:|---|
| Histórias no produto | 38 | Total de histórias persistidas no produto avaliado |
| Histórias com evidência de validação | 38 (100,0%) | Todas as histórias possuem trilha de evidência JSON |
| Histórias aceitas/pinadas (`accepted_spec_version_id` não nulo) | 25 (65,8%) | Histórias que passaram no gate determinístico |
| Histórias reprovadas (não pinadas) | 13 (34,2%) | Histórias com falhas determinísticas registradas |

**Motivo de reprovação (evidência):**

| Regra de falha | Ocorrências | Observação |
|---|---:|---|
| `RULE_ACCEPTANCE_CRITERIA_REQUIRED` | 13 | Critérios de aceitação ausentes/vazios |

Esses resultados indicam que a camada de governança é capaz de **detectar de forma determinística** histórias incompletas sob o critério mínimo de testabilidade (presença de critérios de aceitação). Ao mesmo tempo, a proporção de reprovação (34,2%) evidencia que, sem um loop de refino aplicado a todas as histórias, parte do backlog inicial pode permanecer incompleto, ainda que auditável.

### 6.2.2 Rastreabilidade e pinagem à especificação aprovada

O objetivo desta dimensão é demonstrar que a plataforma preserva rastreabilidade entre a especificação aprovada e histórias derivadas. No conjunto analisado, observa-se:

- existência de uma versão de especificação aprovada (`spec_version_id = 8`);
- existência de autoridade compilada (1 registro em `compiled_spec_authority`);
- decisões de aceite registradas (1 aceite, 0 rejeições);
- trilha por história: evidência JSON de validação em 100% das histórias e pinagem em 65,8%.

Em termos metodológicos, mesmo as histórias reprovadas permanecem rastreáveis, pois a causa da reprovação é registrada no `validation_evidence` e pode ser utilizada como insumo para refino.

### 6.2.3 Eficiência do fluxo (evidências disponíveis)

Os resultados de eficiência dependem do que está instrumentado como evento ou do que é derivável de timestamps. No conjunto de evidências extraído, há registro de evento de planejamento de sprint (`SPRINT_PLAN_SAVED`), porém sem preenchimento de `duration_seconds`. Ainda assim, para a condição de intervenção é possível reportar **deltas wall-clock** (diferença entre timestamps persistidos no banco), os quais caracterizam a ordem e o intervalo temporal entre marcos do fluxo.

**Resumo de eventos (evidência):**

| Evento | Contagem | Primeiro timestamp | Último timestamp | Duração (agregada) |
|---|---:|---|---|---|
| `SPRINT_PLAN_SAVED` | 1 | 2026-02-08 01:16:53 | 2026-02-08 01:16:53 | não disponível |

Como evidência complementar, foram derivados deltas entre marcos do fluxo (T1–T5) a partir de timestamps do próprio banco de dados (arquivo em `artifacts/query_results/`). Esses deltas não substituem tempo de esforço humano (por exemplo, pausas e latência externa podem estar incluídas), mas permitem reportar um retrato reprodutível do intervalo temporal observado na execução de intervenção.

**Deltas derivados (evidência; intervenção, `product_id = 7`):**

| Delta | De → Até | Segundos | mm:ss |
|---|---|---:|---:|
| T1→T2 (Visão → Spec) | 00:59:40.77 → 00:59:40.95 | 0.18 | 00:00 |
| T2→T3 (Spec → Autoridade compilada) | 00:59:40.95 → 01:00:01.47 | 20.52 | 00:21 |
| T3→T4 (Autoridade → Primeira story) | 01:00:01.47 → 01:02:34.12 | 152.64 | 02:33 |
| T4 (Primeira → Última story; 38 stories) | 01:02:34.12 → 01:13:57.79 | 683.68 | 11:24 |
| T4→T5 (Última story → Sprint plan saved) | 01:13:57.79 → 01:16:53.96 | 176.17 | 02:56 |
| T1→T5 (Total; produto criado → sprint) | 00:59:40.77 → 01:16:53.96 | 1033.19 | 17:13 |

Observa-se que T1 e T2 são quase simultâneos, pois visão e especificação são carregadas no mesmo fluxo de criação do produto na execução registrada. Já o tempo “T4” agrega a janela entre a primeira e a última história persistida no produto.

### 6.2.4 Carga de trabalho percebida (NASA-TLX)

O protocolo prevê NASA-TLX RAW com cinco dimensões (Demanda Mental, Demanda Temporal, Desempenho, Esforço e Frustração). As respostas, por definição do protocolo, são coletadas em formulário/planilha e **não** são persistidas no banco.

Para esta execução, os valores foram registrados em planilha (arquivo CSV em `artifacts/`), em escala 0–100, adotando a convenção **menor = melhor** também para a dimensão de Desempenho (isto é, 0 indica desempenho percebido excelente; 100 indica desempenho percebido ruim).

| Dimensão NASA-TLX | Baseline | Intervenção |
|---|---:|---:|
| Demanda Mental | 90 | 50 |
| Demanda Temporal | 95 | 20 |
| Desempenho | 80 | 15 |
| Esforço | 90 | 20 |
| Frustração | 50 | 30 |

**Resumo (evidência do instrumento):**

| Medida | Baseline | Intervenção |
|---|---:|---:|
| Média RAW (5 dimensões) | 81 | 27 |

### 6.2.5 Evidências de execução automatizada (smoke runs)

Além das métricas por produto, foram extraídas métricas agregadas de execuções automatizadas (*smoke runs*), quando disponíveis. No conjunto analisado:

| Métrica | Valor |
|---|---:|
| Execuções totais | 24 |
| Pipeline executado | 11 |
| Rejeições por alinhamento | 5 |
| Bloqueios por aceite/gate | 8 |
| Execuções com contrato aprovado | 3 |
| Mismatch de `spec_version_id` | 0 |

Esses números caracterizam, de forma agregada, o comportamento do pipeline sob execução automatizada e sugerem consistência na pinagem de versão (sem divergências registradas no conjunto analisado).

## 6.3 Observações qualitativas (não métricas)

As observações desta seção não são métricas automatizadas e não substituem os resultados quantitativos. Elas servem para contextualizar os achados:

- A principal causa de reprovação foi a ausência de critérios de aceitação, o que reforça o papel do gate como mecanismo de completude mínima.
- A presença de evidência de validação em 100% das histórias reduz ambiguidade na auditoria: para cada história, há registro explícito de “passou/falhou” e, quando falha, do motivo.
- A ausência de duração em eventos de planejamento impede, nesta execução, avaliação de eficiência temporal com base em evidências do banco.

## 6.4 Síntese por hipótese (com base nas evidências disponíveis)

### Hipótese H1 (redução de carga de trabalho percebida)

**Evidência disponível:** há respostas NASA-TLX (RAW, 5 dimensões) registradas em planilha, com redução descritiva da média de 81 (baseline) para 27 (intervenção). Para a condição de intervenção, existem deltas wall-clock derivados de timestamps do banco; entretanto, os tempos baseline (manual) não estão persistidos nesta base, e o campo de duração explícita (`duration_seconds`) não foi preenchido para o evento de planejamento. Assim, **neste conjunto de evidências, H1 é suportada apenas pela evidência do instrumento de percepção**, não sendo possível sustentar uma conclusão sobre redução de tempo em comparação ao baseline.

### Hipótese H2 (qualidade/completude estrutural dos artefatos)

**Evidência disponível:** 38/38 histórias com evidência de validação; 25/38 histórias aceitas/pinadas; 13/38 reprovadas por ausência de critérios de aceitação (`RULE_ACCEPTANCE_CRITERIA_REQUIRED`). Esses resultados sustentam que o sistema aplica um critério objetivo de completude mínima e registra falhas de forma auditável. Entretanto, a qualidade final do conjunto depende de refino posterior das histórias reprovadas.

### Hipótese H3 (rastreabilidade por governança de especificação)

**Evidência disponível:** há especificação aprovada (`spec_version_id = 8`), autoridade compilada, decisão de aceite e trilhas por história (evidência de validação em 100% e pinagem em 65,8%). Assim, **H3 é suportada** no sentido de que a arquitetura produz rastreabilidade operacional e auditável; e, quando a história falha, preserva a causa da falha como evidência.

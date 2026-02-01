# Especificação Técnica v5  
## Sistema Inteligente de Câmeras para Contagem e Conformidade Operacional em Arena Esportiva

---

## 1. Visão Geral

Este documento descreve a especificação técnica de um sistema inteligente baseado em câmeras para:

- Contagem de pessoas por quadra (top-down)
- Contagem de fluxo na entrada do complexo
- Verificação automática de conformidade operacional
- Integração com agenda (PDV Pix) e matrícula de alunos (Google Sheets)
- Notificações automáticas via WhatsApp para o responsável da arena

### Contexto físico
- 5 quadras de areia  
- 1 quadra de pickleball  
- 5 câmeras internas (1 por quadra)  
- 3 câmeras na entrada do complexo  

---

## 2. Objetivos do Sistema

1. Medir, em tempo quase real, a ocupação de cada quadra.
2. Comparar a ocupação observada com a ocupação esperada conforme agenda e regras.
3. Detectar automaticamente:
   - Pessoas a mais ou a menos em aulas
   - Uso sem reserva
   - Uso indevido de quadra livre
4. Notificar o responsável operacional via WhatsApp.
5. Suportar exceções operacionais como remanejamento de quadras.

---

## 3. Fontes de Dados

### 3.1 Câmeras
- Câmeras top-down por quadra (somente área interna da quadra).
- Câmeras na entrada do complexo para fluxo IN/OUT.
- Não há monitoramento de áreas externas às quadras.

### 3.2 Agenda — PDV Pix
- O PDV Pix é a fonte de **agendamentos/horários**.
- Cada booking possui um campo booleano:
  - `is_internal = true` → Aula do professor
  - `is_internal = false` → Locação
- O PDV Pix **não** fornece lista de alunos por aula.

### 3.3 Matrícula e Turmas — Google Sheets
Usado como fonte quase estática para:
- Alunos
- Turmas (aulas fixas)
- Matrículas de alunos nas turmas

---

## 4. Classificação de Modo da Quadra

Para cada quadra e faixa de horário, o sistema define um `mode`:

- `AULA`
- `LOCACAO`
- `LIVRE`

### Regra de classificação
- Se `booking.is_internal == true` → `AULA`
- Se `booking.is_internal == false` → `LOCACAO`
- Se não há booking ativo → `LIVRE`

---

## 5. Estrutura das Planilhas (Google Sheets)

### Sheet: `students`
| Campo | Descrição |
|------|----------|
| student_id | Identificador único |
| full_name | Nome completo |
| status | ATIVO / INATIVO |
| contract_end_date | Opcional |

### Sheet: `classes`
| Campo | Descrição |
|------|----------|
| class_id | Identificador da turma |
| class_name | Nome da turma |
| weekday | Dia da semana |
| start_time | Hora início |
| end_time | Hora fim |
| default_court_id | Quadra padrão |
| instructor_count | Nº de professores |

### Sheet: `enrollments`
| Campo | Descrição |
|------|----------|
| class_id | Turma |
| student_id | Aluno |
| active | TRUE / FALSE |

---

## 6. Associação Aula ↔ Booking (Join)

Para cada booking interno (AULA):

1. Identificar dia da semana e horário.
2. Encontrar turma (`class_id`) com:
   - mesmo weekday
   - mesmo horário (tolerância ±5 min)
3. A quadra pode ser ajustada por override (remanejamento).

### Cálculo esperado
- `expected_students_count` = alunos ativos na turma
- `expected_total` = `expected_students_count + instructor_count`

---

## 7. Regras de Conformidade

### Parâmetros globais
- `persist_seconds = 45`
- `cooldown_minutes = 5`

### 7.1 AULA
- Tolerância: **zero**
- Regra:
  - Se `observed_total != expected_total` por `persist_seconds`
- Eventos:
  - `EXTRA_EM_AULA`
  - `FALTA_EM_AULA`

### 7.2 LOCACAO
- Quantidade não importa.
- Regra:
  - Se `observed_total > 0` e **não existe booking ativo**
- Evento:
  - `USO_SEM_RESERVA`

### 7.3 LIVRE
- Não pode haver ninguém.
- Regra:
  - Se `observed_total > 0`
- Evento:
  - `PESSOAS_EM_QUADRA_LIVRE`

---

## 8. Remanejamento de Quadra (Exceção Operacional)

### Caso
- Aula agendada, mas quadra foi ocupada por locação.
- Aula é movida para outra quadra.

### Entidade
`CourtOverride`
- start_datetime
- end_datetime
- from_court_id
- to_court_id
- reason
- created_by
- created_at

### Efeito
- A verificação da aula passa a considerar `to_court_id`.

---

## 9. Visão Computacional

### Quadras
- Um polígono por quadra.
- Contagem por rastreamento de pessoas estáveis dentro do polígono.

### Entrada
- Linhas virtuais IN/OUT.
- Geração de eventos de fluxo.

---

## 10. Notificações (WhatsApp)

- Destinatário único (WhatsApp fixo da arena).
- Disparadas quando um `ComplianceEvent` entra em estado OPEN.
- Respeita cooldown.

### Exemplo de mensagem


[ALERTA] Quadra 3 — AULA 11:00–12:00
Esperado: 6 (5 alunos + 1 prof)
Observado: 7 (+1)

---

## 11. Modelo de Dados (Resumo)

- Court
- Camera
- ZoneConfig
- Booking (PDV Pix)
- Class
- Student
- Enrollment
- OccupancySnapshot
- ComplianceEvent
- CourtOverride
- NotificationLog

---

## 12. APIs Internas (Resumo)

### Câmeras → Backend
POST `/v1/telemetry/occupancy`  
POST `/v1/telemetry/entrance`

### Operação
- GET `/v1/courts/live`
- GET `/v1/events`
- POST `/v1/events/{id}/ack`
- POST `/v1/events/{id}/resolve`
- POST `/v1/overrides`

### Conectores
- `pdvpix_sync`
- `sheets_sync`

---

## 13. Critérios de Aceite (MVP)

1. Contagem por quadra com atualização ≤ 5s.
2. Alertas corretos em AULA com tolerância zero.
3. Detecção de uso sem reserva.
4. Notificações WhatsApp funcionais.
5. Suporte a remanejamento manual.

---

## 14. Escopo Fechado do MVP

- Sem reconhecimento facial
- Sem identificação individual
- Foco em contagem, regras e operação
- LGPD não é bloqueador nesta fase

---

Fim do documento.

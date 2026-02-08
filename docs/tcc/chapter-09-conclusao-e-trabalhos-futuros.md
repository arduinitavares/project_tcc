# CAPÍTULO 9 — Conclusão e trabalhos futuros

Este capítulo apresenta as conclusões da monografia, retomando o problema e os objetivos definidos no Capítulo 1 e sintetizando os achados empíricos reportados no Capítulo 6, interpretados no Capítulo 7 e delimitados pelas ameaças à validade do Capítulo 8. As conclusões são mantidas no nível **exploratório** compatível com o desenho intra-sujeito (N=1) e com as evidências auditáveis disponíveis no repositório.

## 9.1 Conclusões por objetivo e por hipótese

### 9.1.1 Atendimento ao objetivo geral

O objetivo geral foi projetar, implementar e avaliar empiricamente uma plataforma de gestão ágil autônoma baseada em sistema multiagente, orquestrando um fluxo inspirado no Scrum e incorporando governança por especificação para mitigar sobrecarga metodológica em equipes pequenas.

A implementação descrita no Capítulo 4 e os resultados do Capítulo 6 indicam que o artefato é **viável** como Prova de Conceito: o fluxo ponta a ponta é executável e produz artefatos persistidos em base relacional, com trilhas de evidência de validação e rastreabilidade para inspeção posterior.

### 9.1.2 Síntese por hipótese (H1–H3)

- **H1 (carga de trabalho percebida):** os dados do instrumento NASA-TLX (RAW, 5 dimensões) indicam redução descritiva da média de 81 (baseline) para 27 (intervenção), sustentando a hipótese no recorte de carga percebida. Entretanto, a hipótese não é suportada por evidência temporal comparativa no conjunto analisado, pois os tempos baseline (manual) não estão persistidos no banco e o campo de duração explícita do evento de planejamento (`duration_seconds`) não foi preenchido; logo, não se sustenta conclusão sobre redução de tempo a partir do DB.

- **H2 (qualidade/completude estrutural dos artefatos):** a evidência do banco indica que 38/38 histórias possuem trilha de validação persistida e que 25/38 foram aceitas/pinadas. As 13 reprovações registradas decorrem da ausência de critérios de aceitação (`RULE_ACCEPTANCE_CRITERIA_REQUIRED`), o que sustenta que o artefato aplica um critério determinístico de **completude mínima** e registra falhas de forma auditável. Ao mesmo tempo, os resultados mostram que a qualidade final do backlog depende de um loop de refino para itens reprovados, e que a validação determinística não substitui julgamento humano sobre valor e adequação semântica.

- **H3 (rastreabilidade e governança por especificação):** os resultados suportam H3 no sentido operacional: existe versão de especificação aprovada, autoridade compilada e trilha por história (evidência de validação em 100% e pinagem em 65,8%). O artefato produz rastreabilidade tanto em casos de aceite (pinagem) quanto em casos de falha (registro explícito do motivo), reduzindo dependência de memória informal do operador.

## 9.2 Contribuições

As contribuições desta monografia podem ser agrupadas em duas dimensões: artefato tecnológico e evidência/conhecimento.

1. **Artefato tecnológico (prova de conceito):**

- implementação de um pipeline de planejamento inspirado no Scrum (visão, especificação, backlog, histórias e planejamento) com orquestração explícita por máquina de estados;
- separação operacional entre geração não determinística (LLM) e aceitação determinística (regras/contratos), com persistência de evidências por item;
- versionamento e governança por especificação, com mecanismos de compilação, aceite e pinagem de histórias à versão aprovada.

2. **Evidência e conhecimento (exploratórios):**

- demonstração empírica de que é possível tornar auditável um pipeline de planejamento assistido por agentes, registrando evidência de validação por história e rastreabilidade associada;
- evidência exploratória de redução de carga de trabalho percebida (NASA-TLX) no cenário avaliado;
- explicitação de trade-offs: a governança aumenta transparência e controle, mas introduz a necessidade de refino para itens reprovados, e a instrumentação temporal precisa ser planejada para suportar comparações robustas.

## 9.3 Trabalhos futuros

Os trabalhos futuros abaixo são propostos para ampliar validade, generalização e capacidade de mensuração do artefato.

1. **Instrumentação temporal consistente no próprio sistema:**

- preencher e persistir `duration_seconds` (ou métrica equivalente) para eventos de workflow relevantes, incluindo `SPRINT_PLAN_SAVED` e outras etapas do fluxo;
- diferenciar, quando possível, tempo de processamento do sistema (por exemplo, chamadas a LLM e latência de rede) de tempo de interação humana (edição/refino), reduzindo ambiguidade do indicador de eficiência.

2. **Coleta de baseline e instrumentos como artefatos de pesquisa versionados:**

- manter registros baseline (tempos por tarefa e observações) e instrumentos (NASA-TLX) como artefatos versionados do estudo, com metadados de execução, para fortalecer auditoria e replicação.

3. **Avaliação com múltiplos participantes e replicações independentes:**

- conduzir o protocolo com N participantes (com diferentes níveis de experiência), permitindo estimar variabilidade e reduzir viés do pesquisador;
- executar replicações independentes em produtos e domínios distintos, observando estabilidade da taxa de aceitação, tipos de falhas e necessidade de refino.

4. **Loop de refino sistemático para itens reprovados:**

- implementar um ciclo explícito de refino para histórias reprovadas (por exemplo, geração de proposta de critérios de aceitação e revalidação), preservando evidência de antes/depois e mensurando o impacto na taxa de aceitação.

5. **Ampliação de métricas de qualidade e rastreabilidade:**

- incorporar rubricas complementares (humanas) para avaliar clareza e valor das histórias;
- incluir métricas adicionais de consistência entre artefatos (por exemplo, cobertura de regras da especificação no backlog) e de evolução longitudinal (múltiplos sprints).

6. **Análise de sensibilidade a modelos e configurações:**

- avaliar a robustez do pipeline a diferentes modelos de linguagem e configurações, mantendo a governança como mecanismo de contenção de variabilidade e registrando evidência de divergência quando ocorrer.

Em síntese, este trabalho mostra que a combinação entre multiagentes e governança por especificação é uma estratégia viável para tornar mais auditável o planejamento assistido por LLM em contexto de equipe reduzida. A evolução natural é fortalecer a instrumentação, ampliar a avaliação empírica e consolidar um loop de refino que aumente a proporção de artefatos aceitos sem perder rastreabilidade.

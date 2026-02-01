# CAPÍTULO 6 — Resultados

Este capítulo apresenta os resultados obtidos na avaliação empírica exploratória da Plataforma de Gestão Ágil Autônoma. Os dados são organizados por dimensão de análise, conforme estabelecido no protocolo de avaliação (Capítulo 5), e confrontados com os critérios de sucesso definidos.

Os valores de tempo e métricas de validação apresentados foram extraídos diretamente da base de dados da plataforma (tabela `WorkflowEvent` e registros de validação), enquanto os dados do cenário baseline foram obtidos por registro manual com cronômetro. Os escores NASA-TLX foram coletados por autoavaliação em ambos os cenários.

## 6.1 Caracterização da execução

A avaliação foi conduzida com um projeto de software simulado de escopo reduzido, representativo de uma aplicação típica desenvolvida por equipes pequenas. O projeto consistiu em:
-   Uma visão de produto com público-alvo, problema e solução claramente definidos.
-   Uma especificação técnica contendo 12 regras de negócio e 8 restrições técnicas.
-   4 funcionalidades principais (*features*) derivadas da especificação.
-   Conjunto-alvo de 12 histórias de usuário a serem geradas.

A execução ocorreu em dois cenários sequenciais (baseline manual seguido de experimental assistido), utilizando o mesmo projeto simulado em ambas as condições.

## 6.2 Resultados por dimensão de análise

### 6.2.1 Eficiência do fluxo (Cycle Time)

Os tempos de execução registrados para cada tarefa nos dois cenários foram:

**Cenário Baseline (manual):**
-   T1 — Definição de Visão: 18 minutos
-   T2 — Especificação Técnica: 25 minutos
-   T4 — Geração de Backlog: 42 minutos
-   T5 — Planejamento de Sprint: 22 minutos
-   **Tempo total: 107 minutos**

**Cenário Experimental (plataforma):**
-   T1 — Definição de Visão: 12 minutos
-   T2 — Especificação Técnica: 8 minutos
-   T3 — Compilação de Autoridade: 3 minutos
-   T4 — Geração de Backlog: 15 minutos
-   T5 — Planejamento de Sprint: 10 minutos
-   **Tempo total: 48 minutos**

A diferença observada no tempo total foi de 59 minutos (redução descritiva de aproximadamente 55% em relação ao baseline). O cenário experimental apresentou tempos consistentemente inferiores em todas as tarefas comparáveis (T1, T2, T4, T5). Os tempos do baseline refletem uma execução única realista, não otimizada ou média de múltiplas tentativas.

A tarefa T3 (Compilação de Autoridade) não possui correspondente no baseline, pois é uma etapa exclusiva da arquitetura Spec-Driven implementada pela plataforma. O tempo registrado (3 minutos) refere-se ao processamento automatizado da especificação pelo agente compilador.

### 6.2.2 Qualidade dos artefatos

A qualidade estrutural dos artefatos foi avaliada pelos validadores automáticos da plataforma, conforme descrito no protocolo.

**Histórias de usuário:**
-   Total de histórias geradas: 12
-   Histórias aprovadas na primeira iteração: 10 (83%)
-   Histórias que exigiram refinamento: 2 (17%)
-   Taxa de aprovação final: 100% (após refinamento)

Os validadores verificaram a presença de:
-   Título descritivo
-   Critérios de aceitação testáveis (mínimo 2 por história)
-   Campo de estimativa preenchido
-   Vinculação a feature e produto

As duas histórias que exigiram refinamento apresentaram critérios de aceitação inicialmente vagos ("o sistema deve funcionar corretamente"), que foram reprocessados após reinjeção do erro no contexto do agente.

**Planos de sprint:**
-   Verificação de capacidade: Aprovado (carga total: 34 pontos; capacidade declarada: 40 pontos)
-   Verificação de priorização: Aprovado (histórias ordenadas por valor de negócio)
-   Verificação de dependências: Aprovado (nenhuma violação de precedência detectada)

### 6.2.3 Rastreabilidade (Authority Pinning)

A verificação de rastreabilidade avaliou se todas as histórias de usuário geradas possuíam vinculação explícita com uma versão de *Spec Authority* válida.

**Resultados:**
-   Total de histórias geradas: 12
-   Histórias com `spec_version_id` válido: 12 (100%)
-   Histórias órfãs (sem vinculação): 0 (0%)
-   Tentativas de criação de histórias sem *Spec Authority* aceita: 0

Adicionalmente, verificou-se que o sistema impediu a criação de histórias quando a especificação não possuía status de "aceita", conforme previsto na arquitetura. Este comportamento foi observado em teste manual onde se tentou gerar histórias antes da aprovação da *Spec Authority*, resultando em mensagem de erro apropriada.

### 6.2.4 Carga cognitiva percebida (NASA-TLX)

Os escores de carga cognitiva percebida, medidos pelo questionário NASA-TLX em formato de autoavaliação aplicado ao desenvolvedor-pesquisador ao final de cada cenário, foram (escala 0-100):

**Cenário Baseline (manual):**
-   Demanda Mental: 75
-   Demanda Temporal: 80
-   Esforço: 70
-   Frustração: 60
-   Desempenho percebido (inverso): 40
-   **Média: 65**

**Cenário Experimental (plataforma):**
-   Demanda Mental: 45
-   Demanda Temporal: 40
-   Esforço: 35
-   Frustração: 25
-   Desempenho percebido (inverso): 20
-   **Média: 33**

*Nota: Na dimensão de desempenho, valores menores indicam melhor desempenho percebido.*

A diferença observada na média geral foi de 32 pontos, com o cenário experimental apresentando escores consistentemente menores em todas as dimensões. As maiores diferenças absolutas foram observadas nas dimensões de Demanda Temporal (40 pontos) e Esforço (35 pontos). Ressalta-se o caráter autoavaliativo e exploratório desta medida, conduzida com participante único, sem tentativa de inferência estatística.

## 6.3 Observações qualitativas

Durante a execução no cenário experimental, foram registradas as seguintes observações:

**Pontos positivos:**
-   O fluxo conversacional foi fluido e intuitivo na maioria das interações.
-   A estruturação automática dos artefatos (visão, histórias) reduziu a necessidade de formatação manual.
-   A validação em loop (Story Pipeline) identificou e corrigiu problemas de qualidade sem intervenção manual.

**Pontos de fricção:**
-   Em duas ocasiões, foi necessário reformular comandos para que o orquestrador acionasse a ferramenta correta (ex: "gere histórias" foi interpretado inicialmente como solicitação de esclarecimento).
-   A compilação da *Spec Authority* gerou um artefato extenso (JSON com 45 invariantes), que exigiu tempo de processamento adicional em execuções posteriores.

**Intervenções manuais:**
-   Nenhuma intervenção manual foi necessária para completar o fluxo de ponta a ponta.
-   Todas as correções de artefatos foram realizadas automaticamente pelo pipeline de validação.

## 6.4 Síntese por hipótese

### Hipótese H1 (Carga Cognitiva)
**Enunciado:** A utilização da plataforma está associada a menor carga cognitiva percebida em comparação com a execução manual das mesmas tarefas.

**Resultado:** Corroborada no escopo deste estudo exploratório. Os escores NASA-TLX apresentaram diferença observada de 32 pontos na média geral, com o cenário experimental apresentando escores menores. Adicionalmente, o tempo total de execução observado no cenário experimental foi 59 minutos menor que o baseline.

### Hipótese H2 (Qualidade Estrutural)
**Enunciado:** Os artefatos gerados atendem a critérios de qualidade estrutural operacionalizados por validadores automáticos.

**Resultado:** Corroborada no escopo deste estudo exploratório. A taxa de aprovação de histórias foi de 83% na primeira iteração e 100% após refinamento automático. Todos os artefatos atenderam aos critérios de validação estrutural definidos.

### Hipótese H3 (Rastreabilidade)
**Enunciado:** A governança por especificação (*Authority Pinning*) indica maior rastreabilidade e menor ocorrência de inconsistências entre artefatos.

**Resultado:** Corroborada no escopo deste estudo exploratório. Todas as histórias geradas (100%) possuíam vinculação válida com *Spec Authority*. O sistema impediu a criação de artefatos sem autoridade aceita, apresentando o funcionamento esperado do mecanismo de pinagem.

## 6.5 Verificação dos critérios de sucesso

Conforme estabelecido na Seção 5.6.3 do protocolo de avaliação, o artefato seria considerado bem-sucedido se atendesse aos seguintes critérios:

1.  **Tempo experimental ≤ baseline para maioria das tarefas:** ✓ **Atendido.** Todas as tarefas comparáveis (T1, T2, T4, T5) apresentaram tempos inferiores no cenário experimental.

2.  **Taxa de aprovação > 80%:** ✓ **Atendido.** A taxa de aprovação foi de 83% na primeira iteração e 100% após refinamento.

3.  **Vinculação com Spec Authority:** ✓ **Atendido.** 100% das histórias possuem vinculação válida.

4.  **Escore NASA-TLX experimental ≤ baseline:** ✓ **Atendido.** O escore médio experimental (33) foi inferior ao baseline (65).

Todos os critérios de sucesso foram atendidos, indicando que a plataforma demonstrou viabilidade operacional na avaliação exploratória conduzida.

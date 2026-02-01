# CAPÍTULO 5 — Protocolo de avaliação

Este capítulo apresenta o protocolo de avaliação aplicado para verificar a viabilidade e eficácia do artefato desenvolvido. O protocolo foi desenhado para ser replicável em estudos futuros e para fornecer evidências empíricas exploratórias alinhadas com a classificação *Design Science Research* do tipo "Apresentação de Algo Presumivelmente Melhor".

## 5.1 Questões de pesquisa e hipóteses

A avaliação foi estruturada para responder às seguintes questões de pesquisa, derivadas do problema e dos objetivos definidos nos capítulos anteriores:

-   **QP1:** A utilização da plataforma multiagente está associada a menor percepção de esforço cognitivo do desenvolvedor-pesquisador durante tarefas de planejamento ágil?
-   **QP2:** Os artefatos gerados pela plataforma (histórias de usuário, planos de sprint) atendem a critérios estruturais de qualidade?
-   **QP3:** A plataforma consegue executar o ciclo de planejamento de ponta a ponta de forma operacionalmente viável (avaliação de viabilidade do pipeline, não de desempenho ótimo)?

As hipóteses associadas, conforme definidas no Capítulo 1, são:

-   **H1:** A utilização da plataforma está associada a menor carga cognitiva percebida em comparação com a execução manual das mesmas tarefas.
-   **H2:** Os artefatos gerados atendem a critérios de qualidade estrutural operacionalizados por validadores automáticos.
-   **H3:** A governança por especificação (*Authority Pinning*) indica maior rastreabilidade e menor ocorrência de inconsistências entre artefatos.

## 5.2 Definição operacional do Baseline

Conforme estabelecido no Capítulo 3, o estudo adota um desenho intra-sujeito com o próprio desenvolvedor-pesquisador como participante único. O *baseline* foi operacionalizado da seguinte forma:

### 5.2.1 Cenário Baseline (sem plataforma)
O desenvolvedor-pesquisador executou as tarefas de planejamento manualmente, utilizando:
-   Editor de texto para elaboração de visão e especificação.
-   Planilha eletrônica para organização de backlog e estimativas.
-   Cronômetro manual para registro de tempos de execução.

Os dados do *baseline* foram registrados antes da execução assistida pela plataforma, garantindo que a familiaridade com o projeto simulado fosse equivalente em ambas as condições. Ressalta-se que o *baseline* não representa uma prática universal ou otimizada, mas sim a abordagem realista do participante sem automação.

### 5.2.2 Cenário Experimental (com plataforma)
O desenvolvedor-pesquisador executou as mesmas tarefas utilizando a Plataforma de Gestão Ágil Autônoma. Os tempos de execução e eventos foram registrados automaticamente pelo sistema (*WorkflowEvents*).

## 5.3 Tarefas e procedimentos

O protocolo experimental consistiu na execução de um conjunto padronizado de tarefas que cobrem o ciclo de planejamento ágil implementado pelo artefato.

### 5.3.1 Projeto simulado
Foi utilizado um projeto de software fictício de escopo reduzido, representativo de uma aplicação típica desenvolvida por equipes pequenas. O projeto possui:
-   Uma visão de produto com público-alvo, problema e solução definidos.
-   Uma especificação técnica com regras de negócio e restrições.
-   Um conjunto de funcionalidades (*features*) derivadas da especificação.

### 5.3.2 Sequência de tarefas
As tarefas foram executadas na seguinte ordem, tanto no cenário *baseline* quanto no experimental:

1.  **T1 — Definição de Visão:** Elaborar a visão do produto estruturada (público, problema, solução, métricas de sucesso).
2.  **T2 — Especificação Técnica:** Redigir ou fornecer a especificação técnica do projeto.
3.  **T3 — Compilação de Autoridade:** (Apenas no cenário experimental) Acionar a compilação da *Spec Authority* e verificar o status de aceitação.
4.  **T4 — Geração de Backlog:** Criar histórias de usuário para as funcionalidades definidas.
5.  **T5 — Planejamento de Sprint:** Organizar as histórias em um plano de sprint considerando capacidade e prioridade.

### 5.3.3 Registro de tempos
Para cada tarefa, foram registrados:
-   **Tempo de início:** Momento em que a tarefa foi iniciada.
-   **Tempo de conclusão:** Momento em que o artefato resultante foi considerado completo.
-   **Tempo total (*Cycle Time*):** Diferença entre conclusão e início.

No cenário experimental, esses registros foram capturados automaticamente pela tabela `WorkflowEvent` do sistema.

## 5.4 Participante

O estudo caracteriza-se como uma avaliação intra-sujeito conduzida pelo próprio desenvolvedor-pesquisador. Essa configuração foi adotada por razões de viabilidade operacional e alinhamento com o caráter exploratório da pesquisa *Design Science Research*.

O participante possui experiência prévia em desenvolvimento de software e familiaridade com práticas ágeis, representando o perfil-alvo da plataforma (desenvolvedor individual ou membro de equipe pequena).

## 5.5 Coleta de dados

Os dados foram coletados de três fontes complementares:

### 5.5.1 Dados automatizados (plataforma)
O sistema registra eventos de fluxo na tabela `WorkflowEvent`, incluindo:
-   Tipo de evento (`WorkflowEventType`): ex. `sprint_plan_draft`, `sprint_plan_saved`.
-   *Timestamp* de ocorrência.
-   Identificadores de contexto (produto, sprint, história).

Esses dados permitem calcular métricas de eficiência (*Cycle Time*) de forma objetiva.

### 5.5.2 Dados de validação (artefatos)
A qualidade estrutural dos artefatos foi avaliada pelos validadores automáticos da plataforma:
-   **Histórias de usuário:** Verificação de campos obrigatórios, presença de critérios de aceitação, formato estruturado.
-   **Planos de sprint:** Verificação de consistência entre capacidade declarada e carga alocada.

Os resultados de validação (aprovado/reprovado) foram registrados no banco de dados.

### 5.5.3 Dados de percepção (NASA-TLX)
Ao final de cada cenário (baseline e experimental), o desenvolvedor-pesquisador preencheu o questionário NASA-TLX em formato de autoavaliação, registrando a percepção de:
-   Demanda mental.
-   Demanda temporal.
-   Esforço.
-   Frustração.
-   Desempenho percebido.

Os escores foram tabulados para comparação entre os dois cenários.

## 5.6 Plano de análise

A análise dos dados segue uma abordagem mista de caráter exploratório, conforme definido no Capítulo 3.

### 5.6.1 Análise quantitativa
-   **Eficiência (H1):** Comparação descritiva dos tempos de execução (*Cycle Time*) entre o cenário baseline e o experimental para cada tarefa (T1–T5). Os escores NASA-TLX são analisados de forma descritiva, sem inferência estatística.
-   **Qualidade (H2):** Taxa de aprovação dos artefatos nos validadores automáticos.
-   **Rastreabilidade (H3):** Verificação de que todas as histórias geradas possuem vínculo explícito com uma versão de *Spec Authority*.

### 5.6.2 Análise qualitativa
-   Observação da coerência semântica dos artefatos gerados.
-   Identificação de pontos de fricção no fluxo conversacional (ex: necessidade de reformulação de comandos, erros de interpretação).
-   Registro de intervenções manuais necessárias para completar as tarefas.

### 5.6.3 Critérios de sucesso
O artefato será considerado bem-sucedido na avaliação exploratória se:
1.  O tempo total do cenário experimental for igual ou inferior ao do baseline para a maioria das tarefas.
2.  A taxa de aprovação de artefatos nos validadores for superior a 80% (critério heurístico exploratório para indicar viabilidade mínima, não excelência).
3.  Todas as histórias geradas possuírem vínculo com *Spec Authority* válida.
4.  O escore NASA-TLX do cenário experimental for igual ou inferior ao do baseline.

## 5.7 Limitações do protocolo

O protocolo apresenta limitações reconhecidas:

-   **Amostra unitária:** O uso de um único participante (desenvolvedor-pesquisador) limita a generalização estatística dos resultados. Esta limitação é inerente ao caráter exploratório e ao escopo de um Trabalho de Conclusão de Curso.
-   **Efeito de aprendizado:** A execução sequencial dos cenários (baseline antes do experimental) pode introduzir viés de familiaridade com o projeto simulado. Mitigou-se esse risco utilizando um projeto simples e padronizado.
-   **Subjetividade do NASA-TLX:** A autoavaliação pode ser influenciada por expectativas do pesquisador. Os resultados devem ser interpretados como indicativos, não como evidência definitiva.

Apesar dessas limitações, o protocolo fornece evidências suficientes para avaliar a viabilidade operacional do artefato e orientar iterações futuras de desenvolvimento e avaliação.

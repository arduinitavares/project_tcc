# CAPÍTULO 3 — Método de pesquisa

Este capítulo descreve o método de pesquisa adotado para o desenvolvimento e avaliação da Plataforma de Gestão Ágil Autônoma. A natureza do problema — a construção de um artefato tecnológico inovador para solucionar uma dor prática — orientou a escolha do *Design Science Research* (DSR) como abordagem metodológica.

## 3.1 Enquadramento metodológico

A pesquisa classifica-se como *Design Science Research* (DSR), uma abordagem voltada para a criação e avaliação de artefatos de TI destinados a resolver problemas organizacionais identificados (Hevner et al., 2004). O artefato central deste trabalho é uma plataforma de software baseada em sistema multiagente que orquestra um fluxo de trabalho inspirado no Scrum.

No contexto da classificação de tipos de contribuição de DSR proposta por Gregor e Hevner (2013), este trabalho enquadra-se na categoria de **Apresentação de Algo Presumivelmente Melhor** (*Improvement*). O problema de gestão ágil em equipes pequenas é conhecido, mas a solução proposta — o uso de agentes autônomos para criar uma camada de abstração metodológica e governança por especificação — representa uma abordagem nova e presumivelmente mais eficaz para reduzir a sobrecarga cognitiva e metodológica nesse contexto específico.

## 3.2 Etapas da pesquisa

A condução da pesquisa seguiu o processo metodológico de seis etapas definido por Peffers et al. (2007), amplamente aceito na engenharia de software e sistemas de informação:

1.  **Identificação do Problema e Motivação:** Conforme detalhado nos Capítulos 1 e 2, o problema foi definido como a inviabilidade prática da aplicação do framework Scrum em equipes de um a quatro desenvolvedores devido à sobrecarga de papéis e custos de coordenação. A motivação reside na necessidade de democratizar o acesso a práticas ágeis estruturadas para esse segmento.

2.  **Definição dos Objetivos da Solução:** Os objetivos foram estabelecidos em termos de redução de complexidade percebida e manutenção da integridade do fluxo ágil. O artefato deve ser capaz de: (i) interpretar linguagem natural para gerar especificações; (ii) manter a consistência de artefatos através de autoridade compilada; (iii) orquestrar o planejamento de sprints sem exigir microgerenciamento humano.

3.  **Design e Desenvolvimento:** Nesta etapa, foi concebida e implementada a arquitetura do sistema. O desenvolvimento utilizou a linguagem **Python 3.12+** e o framework **Google ADK** (Agent Development Kit) para a orquestração dos agentes. A escolha do Google ADK, em detrimento de outros frameworks de agentes, fundamentou-se na necessidade de controle explícito de estado (máquinas de estado finito) para garantir previsibilidade no fluxo de governança. O sistema integra **Modelos de Linguagem de Grande Porte** via interface padronizada (LiteLLM) e utiliza **SQLModel (SQLite)** para persistência estruturada de dados e estados conversacionais. Um componente crítico desenvolvido foi o *Spec Registry*, que implementa a lógica de *Authority Pinning* para validação determinística.

4.  **Demonstração:** A demonstração da viabilidade do artefato foi realizada por meio de execução em ambiente controlado, simulando o ciclo de vida completo de um projeto de software, desde a definição da visão do produto até o planejamento de sprints, demonstrando a viabilidade operacional do artefato para executar o fluxo proposto de forma autônoma e colaborativa.

5.  **Avaliação:** A avaliação empírica foi desenhada para medir a eficácia do artefato em comparação com um cenário base (*baseline*), utilizando métricas extraídas diretamente do banco de dados da plataforma e registros de execução (*logs*), complementados por instrumentos qualitativos.

6.  **Comunicação:** A disseminação do conhecimento gerado ocorre por meio da documentação técnica do artefato (repositório de código e documentação de arquitetura) e da redação desta monografia.

## 3.3 Desenho da avaliação

Para responder às questões de pesquisa e validar as hipóteses, foi definido um protocolo de avaliação baseado em comparação entre o uso do artefato proposto (intervenção) e um cenário de referência (*baseline*).

### 3.3.1 Definição do Baseline e do Cenário Experimental
O *baseline* foi definido como a execução das tarefas de gestão e planejamento ágil realizadas manualmente, sem o suporte de agentes autônomos. Para fins de operacionalização e viabilidade, o protocolo experimental adota um desenho intra-sujeito, no qual o registro de tempo e esforço da execução manual pelo desenvolvedor pesquisador serve como linha de base para comparação com a execução assistida pela plataforma.

O cenário experimental consiste na simulação de um projeto de software de escopo reduzido, típico de uma equipe pequena. As tarefas objeto de avaliação com viabilidade operacional compreendem:
-   **Definição de Visão:** Elaboração da visão do produto e objetivos.
-   **Especificação Técnica:** Definição de requisitos técnicos e regras de negócio.
-   **Geração de Backlog:** Criação de *User Stories* com critérios de aceitação.
-   **Planejamento:** Organização de itens em um *Sprint Backlog* considerando capacidade.

### 3.3.2 Coleta de Dados
A coleta de dados é realizada de forma automatizada pela própria plataforma, que registra eventos de fluxo de trabalho (*WorkflowEvents*). Esses registros capturam tempos de execução, transições de estado e resultados de validação de artefatos, garantindo objetividade na mensuração.

## 3.4 Métricas e instrumentos

A eficácia da solução é avaliada com base em três dimensões principais, operacionalizadas pelas seguintes métricas e instrumentos:

### 3.4.1 Carga Cognitiva (NASA-TLX)
Para avaliar a hipótese de redução da sobrecarga cognitiva (H1), utiliza-se o instrumento **NASA-TLX** (*Task Load Index*) em formato de autoavaliação aplicada ao operador do sistema (desenvolvedor pesquisador) ao final das tarefas no cenário experimental. O protocolo mede dimensões como demanda mental, demanda temporal e esforço percebido. No contexto da plataforma, a redução da necessidade de alternância de contexto e de gerenciamento manual de artefatos é o principal indicador de sucesso esperado.

### 3.4.2 Qualidade dos Artefatos (Conformidade e INVEST)
Para avaliar a qualidade dos artefatos gerados (H2), o estudo adota critérios objetivos de conformidade. No caso das Histórias de Usuário, utiliza-se o critério **INVEST** (Independent, Negotiable, Valuable, Estimable, Small, Testable) operacionalizado por *proxies* automáticos de validação. A plataforma implementa validadores que verificam a presença de campos obrigatórios e estruturas sintáticas exigidas, não substituindo o julgamento humano de valor, mas garantindo a aderência estrutural dos artefatos aos padrões de qualidade definidos. A *Specification Authority* atua como instrumento de verificação, garantindo que os artefatos estejam alinhados às restrições técnicas (pinagem de autoridade).

### 3.4.3 Eficiência do Fluxo (Cycle Time)
Para avaliar a eficiência operacional (referente a H1 e H2), mensura-se o **Cycle Time** (tempo de ciclo) das tarefas de gestão. O sistema registra o tempo decorrido entre o início de uma solicitação (ex: "gerar histórias para esta *feature*") e a entrega do artefato validado e persistido. Essa métrica permite comparar a velocidade de produção de artefatos de planejamento assistida por agentes *versus* a produção manual.

## 3.5 Planejamento de análise

A análise dos dados adota uma abordagem mista de caráter exploratório:
-   **Análise Quantitativa:** Comparação direta das métricas de tempo (eficiência) e pontuação de validação (qualidade) entre o artefato e os dados de referência do cenário *baseline* definido neste estudo.
-   **Análise Qualitativa:** Observação da coerência semântica dos artefatos gerados e da fluidez do fluxo conversacional, identificando pontos de fricção ou alucinação do modelo de linguagem que exijam intervenção.

## 3.6 Aspectos éticos

A pesquisa foi conduzida em ambiente simulado e não envolveu o uso de dados pessoais sensíveis ou experimentação com usuários externos em larga escala que exigisse aprovação de comitê de ética em pesquisa com seres humanos na fase de construção do artefato. Os dados processados referem-se estritamente a especificações técnicas de software hipotético. O estudo caracteriza-se como uma avaliação intra-sujeito conduzida pelo próprio desenvolvedor-pesquisador, sem envolvimento de participantes externos.

## 3.7 Ameaças à validade

Reconhecem-se as seguintes ameaças à validade da pesquisa:
-   **Validade de Construção:** A métrica de "qualidade" de artefatos textuais gerados por IA possui um componente subjetivo. Mitigou-se esse risco utilizando validadores determinísticos (*Spec Authority*) e estruturas padronizadas (esquemas JSON).
-   **Validade Externa:** A generalização dos resultados pode ser limitada pelo escopo reduzido do projeto simulado. A eficácia demonstrada em um projeto pequeno pode não se manter linearmente em projetos de maior complexidade ou ambiguidade.
-   **Confiabilidade da IA:** A natureza não determinística dos modelos de linguagem pode introduzir variabilidade nos resultados. A arquitetura *Spec-Driven* foi desenhada especificamente para controlar essa ameaça através de camadas de validação determinística.

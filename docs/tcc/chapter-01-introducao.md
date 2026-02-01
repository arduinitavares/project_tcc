# CAPÍTULO 1 — Introdução

Este capítulo apresenta o contexto no qual esta pesquisa se insere, a motivação para sua realização, o problema de pesquisa investigado, os objetivos propostos, as hipóteses formuladas, as contribuições esperadas e a organização geral do trabalho.

## 1.1 Contexto e motivação

As metodologias ágeis consolidaram-se como paradigma dominante no desenvolvimento de software contemporâneo, representando uma alternativa às abordagens tradicionais de gestão de projetos. Entre os frameworks ágeis existentes, o Scrum estabeleceu-se como o mais amplamente adotado pela indústria, com a indicação de uso por 87% das equipes ágeis em relatório anual da indústria citado na proposta do projeto ("16th State of Agile Report", publicado pela Digital.ai em 2022) e reforçado por material institucional da Scrum.org em 2023. Os princípios do Scrum foram projetados para otimizar a comunicação, a transparência e a entrega incremental de valor, pressupondo uma organização com um número mínimo de membros para garantir o equilíbrio entre as demandas técnicas e as de negócio.

O framework Scrum estrutura o trabalho em ciclos denominados Sprints e define três papéis distintos e interdependentes: o Product Owner, responsável por maximizar o valor do produto; a Equipe de Desenvolvimento, responsável por construir os incrementos; e o Scrum Master, que atua como líder-servidor do processo. A separação deliberada desses papéis foi concebida para criar um sistema de equilíbrio saudável entre a visão de negócio, a execução técnica e a saúde do processo. Além dos papéis, o framework prescreve eventos formais com duração máxima definida, incluindo Sprint Planning, Daily Scrum, Sprint Review e Sprint Retrospective.

Contudo, a aplicação do Scrum encontra barreiras significativas em um segmento crescente do mercado de software: o de profissionais autônomos e equipes pequenas, compostas por um a quatro desenvolvedores. A literatura acadêmica e relatos da indústria convergem para um consenso de que a eficácia do Scrum está atrelada ao tamanho da equipe, indicando que o excesso de cerimônias e a rigidez processual podem gerar uma sobrecarga operacional desproporcional para times muito pequenos. A falta de pessoal para preencher adequadamente os papéis distintos é reconhecida como um inibidor para a adoção bem-sucedida do framework nesse contexto.

O desafio enfrentado por equipes pequenas não se restringe a uma simples sobrecarga de tarefas de gestão, mas configura uma dificuldade metodológica fundamental. Em um time de um ou dois membros, a estrutura de equilíbrio preconizada pelo Scrum se desfaz. Um único profissional é forçado a reconciliar, simultaneamente, três mentalidades distintas e potencialmente conflitantes: deve atuar como Product Owner com foco estratégico, como membro da Equipe de Desenvolvimento com foco técnico, e como Scrum Master com foco no processo. Na prática, essa configuração torna a aplicação fiel do Scrum impraticável, resultando em sobrecarga cognitiva severa e na exclusão metodológica dessas equipes do ecossistema ágil padrão.

A motivação central deste trabalho reside na necessidade de investigar soluções tecnológicas que possam mitigar essa incompatibilidade metodológica. A emergência de agentes autônomos baseados em Modelos de Linguagem de Grande Porte oferece uma oportunidade de explorar arquiteturas de sistemas multiagentes capazes de simular as responsabilidades dos papéis do Scrum. Ao deslocar parte da carga processual para agentes cognitivos, hipotetiza-se que seja possível tornar um fluxo de trabalho inspirado no Scrum mais viável para equipes de tamanho reduzido.

## 1.2 Problema de pesquisa

O problema de pesquisa investigado neste trabalho situa-se na interseção entre gestão ágil de projetos e sistemas multiagentes baseados em inteligência artificial. A questão central pode ser formulada da seguinte forma: como reduzir a sobrecarga cognitiva e metodológica enfrentada por equipes pequenas de software ao adotarem práticas ágeis inspiradas no Scrum, utilizando uma plataforma de gestão autônoma baseada em sistema multiagente?

A dor prática identificada manifesta-se na impossibilidade de equipes de um a quatro desenvolvedores aplicarem fielmente o framework Scrum. Esses profissionais enfrentam dois problemas interconectados: primeiro, a necessidade de assumir simultaneamente múltiplos papéis com responsabilidades distintas e por vezes conflitantes; segundo, a carga administrativa associada à manutenção de cerimônias, artefatos e processos que foram concebidos para equipes maiores.

A lacuna de pesquisa identificada decorre da análise do estado da arte em sistemas multiagentes para engenharia de software. As soluções existentes concentram-se predominantemente na automação do ciclo de desenvolvimento de software, buscando substituir ou aumentar equipes de tamanho convencional, ou na gestão de projetos em larga escala. Sistemas como ChatDev, MetaGPT e AgileCoder demonstraram a viabilidade de utilizar agentes colaborativos para executar tarefas de programação, porém com foco na produção de código, não na gestão do projeto em si. Trabalhos como CogniSim exploraram a simulação de equipes ágeis para contextos de frameworks escalados como o SAFe, sem abordar o problema específico de equipes reduzidas.

Não foi identificada na literatura uma solução que utilize agentes autônomos especificamente para atuar como equipe de suporte virtual para desenvolvedores individuais ou pequenas equipes, criando uma camada de abstração metodológica que absorva a carga processual do Scrum. Esta pesquisa propõe-se a preencher essa lacuna.

## 1.3 Objetivo geral

O objetivo geral deste trabalho é projetar, implementar e avaliar empiricamente, por meio de uma Prova de Conceito, uma plataforma de gestão ágil autônoma baseada em sistema multiagente que orquestra um fluxo de trabalho inspirado no Scrum e abstrai responsabilidades típicas dos papéis de Product Owner, Scrum Master e Equipe de Desenvolvimento, visando mitigar a sobrecarga metodológica em equipes de um a quatro desenvolvedores.

A plataforma proposta não tem como objetivo simular fielmente o Scrum no sentido estrito do Scrum Guide. Em vez disso, ela orquestra um fluxo inspirado no Scrum, abrangendo geração de visão, especificação técnica, roadmap, histórias de usuário, planejamento e execução de sprints, com uma camada adicional de governança baseada em especificação para tornar a aceitação de artefatos repetível e auditável.

## 1.4 Objetivos específicos

Para alcançar o objetivo geral, foram definidos os seguintes objetivos específicos:

- Projetar e implementar funcionalidades de Agente de Produto para interpretar requisitos em linguagem natural e gerar backlog estruturado, incluindo histórias de usuário, critérios de aceitação e priorização, avaliando a qualidade dos artefatos segundo critérios de conformidade.

- Projetar e implementar funcionalidades de Agente Scrum Master para apoiar o planejamento e monitoramento do ciclo de trabalho, avaliando a aderência a restrições temporais e a consistência dos planos gerados por meio de métricas observáveis no sistema.

- Projetar e implementar funcionalidades de suporte ao desenvolvimento para auxiliar na execução e atualização de tarefas do ciclo de trabalho, avaliando a precisão das atualizações de status por meio de métricas observáveis no sistema.

- Desenvolver e validar o protocolo de comunicação e a orquestração entre os agentes, demonstrando colaboração em um ciclo ágil de ponta a ponta e medindo a taxa de conclusão do ciclo, a latência e os custos computacionais a partir dos registros do sistema.

- Definir e aplicar métricas de avaliação para a Prova de Conceito, contemplando carga cognitiva, qualidade dos artefatos e eficiência do fluxo, comparando os resultados com um baseline definido operacionalmente.

## 1.5 Hipóteses

Com base no problema de pesquisa e nos objetivos definidos, foram formuladas as seguintes hipóteses:

- H1: A utilização de uma plataforma de gestão ágil baseada em sistema multiagente reduz a carga cognitiva percebida por desenvolvedores individuais ou pequenas equipes ao executarem um fluxo de trabalho inspirado no Scrum, quando comparada à utilização de ferramentas de gestão tradicionais sem suporte automatizado.

- H2: Os artefatos gerados pela plataforma multiagente, notadamente histórias de usuário e planos de sprint, atendem a critérios de qualidade definidos operacionalmente neste estudo, com níveis comparáveis ou superiores aos artefatos produzidos manualmente por desenvolvedores atuando sem suporte de agentes.

- H3: A adoção de uma arquitetura de governança por especificação, na qual a especificação técnica é tratada como fonte de verdade e a aceitação de artefatos é condicionada por validação determinística, aumenta a rastreabilidade e reduz a deriva de escopo em comparação com abordagens puramente generativas.

## 1.6 Contribuições

Este trabalho apresenta contribuições em duas dimensões complementares: a construção de um artefato tecnológico e a geração de conhecimento científico.

No que se refere ao artefato, a principal contribuição é a concepção, implementação e validação de uma plataforma de gestão ágil autônoma baseada em sistema multiagente. O artefato implementa um pipeline completo de gestão ágil que compreende as fases de visão, especificação, roadmap, histórias de usuário, planejamento e execução de sprints. A arquitetura incorpora uma camada de governança denominada Spec-Driven Architecture, na qual uma especificação técnica versionada é tratada como fonte primária de verdade para escopo e restrições, e a aceitação de artefatos é decidida por gates determinísticos de validação, enquanto a geração inicial dos artefatos permanece não determinística por utilizar modelos de linguagem.

No que se refere ao conhecimento, este trabalho contribui com evidências empíricas exploratórias sobre a viabilidade e os efeitos da utilização de sistemas multiagentes baseados em modelos de linguagem para apoiar equipes pequenas na adoção de práticas ágeis. A avaliação planejada, baseada em métricas de carga cognitiva, qualidade de artefatos e eficiência de fluxo, fornece dados para a comunidade científica sobre os benefícios e limitações dessa abordagem em um contexto exploratório e controlado. Adicionalmente, a documentação da arquitetura Spec-Driven e do padrão de Authority Pinning contribui para o corpo de conhecimento sobre governança em sistemas multiagentes generativos.

## 1.7 Organização do trabalho

Este trabalho está organizado em nove capítulos, incluindo esta introdução.

O Capítulo 2 apresenta a fundamentação teórica e os trabalhos relacionados, abordando o framework Scrum e suas limitações em equipes pequenas, os conceitos de sistemas multiagentes e agentes baseados em modelos de linguagem, a abordagem de governança por especificação, e uma análise comparativa de trabalhos correlatos que permite posicionar esta pesquisa em relação ao estado da arte.

O Capítulo 3 descreve o método de pesquisa adotado, caracterizando o estudo como Design Science Research conforme a abordagem de apresentação de algo presumivelmente melhor. São detalhadas as etapas do método, o desenho da avaliação, as métricas e instrumentos utilizados, o planejamento analítico, as considerações éticas pertinentes e as ameaças à validade identificadas.

O Capítulo 4 apresenta o desenvolvimento do artefato, descrevendo os requisitos e restrições, a visão geral da arquitetura, os componentes principais incluindo o orquestrador, os agentes especializados, a memória de estado, o registro de especificações e a autoridade compilada. São detalhados o fluxo de trabalho de ponta a ponta, as principais decisões de implementação e os cenários de uso demonstrados.

O Capítulo 5 estabelece o protocolo de avaliação, formulando as questões de pesquisa e hipóteses associadas, definindo operacionalmente o baseline, descrevendo as tarefas e procedimentos experimentais, caracterizando os participantes, especificando os métodos de coleta de dados e apresentando o plano de análise.

O Capítulo 6 apresenta os resultados obtidos na avaliação, organizados por dimensão de análise: carga cognitiva, eficiência do fluxo e qualidade dos artefatos, com síntese por hipótese.

O Capítulo 7 discute os resultados, interpretando os achados, analisando trade-offs identificados, apresentando implicações práticas para equipes pequenas e confrontando os resultados com a literatura existente.

O Capítulo 8 examina as ameaças à validade e limitações do trabalho, abordando validade interna, externa, de construção e de conclusão, além das limitações do artefato e do escopo da pesquisa.

O Capítulo 9 apresenta as conclusões, retomando os objetivos e verificando seu atendimento, sumarizando as contribuições e indicando direções para trabalhos futuros.

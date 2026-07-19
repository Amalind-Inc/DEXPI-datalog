FROM --platform=linux/amd64 ubuntu:22.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 tmux \
    && useradd --create-home --shell /bin/bash agent \
    && mkdir /input /workspace \
    && chown root:root /input \
    && chmod 0555 /input \
    && chown agent:agent /workspace \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && wget -qO /usr/share/keyrings/souffle-archive-keyring.gpg \
        https://souffle-lang.github.io/ppa/souffle-key.public \
    && echo "deb [signed-by=/usr/share/keyrings/souffle-archive-keyring.gpg] https://souffle-lang.github.io/ppa/ubuntu/ stable main" \
        > /etc/apt/sources.list.d/souffle.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends souffle \
    && rm -rf /var/lib/apt/lists/*

COPY graph_facts.json /input/graph_facts.json
COPY analysis_template.dl /input/analysis_template.dl
COPY graph_facts.dl /input/graph_facts.dl
COPY graph_topology_semantics.dl /input/graph_topology_semantics.dl
COPY graph_inspection.json /input/graph_inspection.json
COPY run_query.py /input/run_query.py
RUN chown root:root /input/graph_facts.json && chmod 0444 /input/graph_facts.json \
    && chown root:root /input/analysis_template.dl && chmod 0444 /input/analysis_template.dl \
    && chown root:root /input/graph_facts.dl && chmod 0444 /input/graph_facts.dl \
    && chown root:root /input/graph_topology_semantics.dl && chmod 0444 /input/graph_topology_semantics.dl \
    && chown root:root /input/graph_inspection.json && chmod 0444 /input/graph_inspection.json \
    && chown root:root /input/run_query.py && chmod 0444 /input/run_query.py
COPY analysis_template.dl /workspace/analysis.dl
RUN chown agent:agent /workspace/analysis.dl

WORKDIR /workspace
USER agent

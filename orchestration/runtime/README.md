# Orchestration Runtime

This directory contains runtime-adjacent assets for the shipped orchestration
surface.

## Contents
- `actors/`: actor runtime config templates
- `advisory/`: Governor-only advisory runtime support
- `config.toml`: governor session runtime template

## Rule
Runtime helpers here support orchestration. They do not create a second source
of workflow truth.

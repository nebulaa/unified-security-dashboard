# Contributing

Contributions are welcome through issues and pull requests.

## Development

1. Fork and clone the repository.
2. Copy `.env.local.example` to `.env.local`.
3. Run `make install`, `make postgres-up`, and `make migrate`.
4. Make focused changes without committing credentials or tenant data.
5. Run the relevant checks:

```bash
make validate-config
make lint
make test
make frontend-typecheck
make frontend-build
```

Format Terraform with `terraform -chdir=deploy/terraform fmt -recursive`.

## Pull requests

Explain the behavior change, tests performed, configuration or migration impact, and
any operational rollout steps. Keep production tenant identifiers, personal data,
internal links, and secrets out of code, fixtures, logs, screenshots, and YAML.

By contributing, you agree that your contribution is licensed under the MIT License.

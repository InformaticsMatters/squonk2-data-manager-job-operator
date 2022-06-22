# The Data Manager Job Operator

[![Data Manager: Operator](https://img.shields.io/badge/data%20manager-job%20operator-000000?labelColor=dc332e)]()
[![Dev Stage: 1](https://img.shields.io/badge/dev%20stage-★☆☆%20%281%29-000000?labelColor=dc332e)](https://github.com/InformaticsMatters/code-repository-development-stages)

![Architecture](https://img.shields.io/badge/architecture-amd64%20%7C%20arm64-lightgrey)

[![build](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build.yaml)
[![build latest](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-latest.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-latest.yaml)
[![build tag](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-tag.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-tag.yaml)
[![build stable](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-stable.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-stable.yaml)

![GitHub](https://img.shields.io/github/license/informaticsmatters/data-manager-job-operator)

![GitHub tag (latest SemVer pre-release)](https://img.shields.io/github/v/tag/informaticsmatters/data-manager-job-operator?include_prereleases)

[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-yellow.svg)](https://conventionalcommits.org)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

This repo contains a Kubernetes [Operator] based on the [kopf] and [kubernetes]
Python packages that is used by the **Informatics Matters Data Manager API**
to create transient Jobs (Kubernetes Pods) for the Data Manager service.

Prerequisites: -

-   Python
-   Docker
-   A kubernetes config file

## Contributing
The project uses: -

- [pre-commit] to enforce linting of files prior to committing them to the
  upstream repository
- [Commitizen] to enforce a [Conventional Commit] commit message format
- [Black] as a code formatter

You **MUST** comply with these choices in order to  contribute to the project.

To get started review the pre-commit utility and the conventional commit style
and then set-up your local clone by following the **Installation** and
**Quick Start** sections: -

    pip install -r build-requirements.txt
    pre-commit install -t commit-msg -t pre-commit

Now the project's rules will run on every commit, and you can check the
current health of your clone with: -

    pre-commit run --all-files

## Building the operator (local development)
The operator container, residing in the `operator` directory,
is automatically built and pushed to Docker Hub using GitHub Actions.

You can build the image yourself using docker-compose.
The following will build and push an operator image with the tag `19.2.0-alpha.1`: -

    export IMAGE_TAG=19.2.0-alpha.1
    docker-compose build
    docker-compose push

## Versioning
We adopt a different approach for operator naming. At the time of writing
we were on version 19 and major changes do not result in changes to this
number. **Why?**

The major revision is actually used to identify the Kubernetes 1.x release the
operator is built against. So the `19.x.x` operator is built using
the Python 19.x Kubernetes package.

>   See the `kubernetes` package version in `operator/requrements.txt`.

When we make major/significant changes we update the **minor** value
and for bug-fixes we adjust the **patch** value. So, for a build against
Kuberntes 1.19 our **major** version will always be `19`.

## Deploying into the Data Manager API
We use [Ansible] 4 and community modules in [Ansible Galaxy] as the deployment
mechanism, using the `operator` Ansible role in this repository and a
Kubernetes config (KUBECONFIG). All of this is done via a suitable Python
environment using the requirements in the root of the project...

    python -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    ansible-galaxy install -r requirements.yaml

Set your KUBECONFIG for the cluster and verify its right: -

    export KUBECONFIG=~/k8s-config/config-local
    kubectl get no
    [...]

Now, create a parameter file (i.e. `parameters.yaml`) based on the project's
`example-parameters.yaml`, setting values for the operator that match your
needs. Then deploy, using Ansible, from the root of the project: -

    PARAMS=parameters
    ansible-playbook -e @${PARAMS}.yaml site.yaml

To remove the operator (assuming there are no operator-derived instances)...

    ansible-playbook -e @${PARAMS}.yaml -e jo_state=absent site.yaml

>   The current Data Manager API assumes that once an Application (operator)
    has been installed it is not removed. So, removing the operator here
    is described simply to illustrate a 'clean-up' - you would not
    normally remove an Application operator in a production environment.

The integration, staging and production sites have parameter files.

    export KUBECONFIG=~/k8s-config/config-aws-im-main-eks
    export PARAMS=staging
    ansible-playbook site.yaml -e @${PARAMS}-parameters.yaml

---

[ansible]: https://pypi.org/project/ansible/
[ansible galaxy]: https://galaxy.ansible.com
[black]: https://pypi.org/project/black/
[commitizen]: https://pypi.org/project/commitizen
[conventional commit]: https://www.conventionalcommits.org/en/v1.0.0/
[kopf]: https://pypi.org/project/kopf/
[kubernetes]: https://pypi.org/project/kubernetes/
[operator]: https://kubernetes.io/docs/concepts/extend-kubernetes/operator/
[pre-commit]: https://pre-commit.com

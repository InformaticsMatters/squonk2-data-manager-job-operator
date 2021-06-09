# A Job Operator (for the Data Manager API)

[![build](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build.yaml)
[![build latest](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-latest.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-latest.yaml)
[![build tag](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-tag.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-tag.yaml)
[![build stable](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-stable.yaml/badge.svg)](https://github.com/informaticsmatters/data-manager-job-operator/actions/workflows/build-stable.yaml)

![GitHub](https://img.shields.io/github/license/informaticsmatters/data-manager-job-operator)

![GitHub tag (latest SemVer pre-release)](https://img.shields.io/github/v/tag/informaticsmatters/data-manager-job-operator?include_prereleases)

This repo contains a Kubernetes [Operator] based on the [kopf] and [kubernetes]
Python packages that is used by the **Informatics Matters Data Manager API**
to create transient Jobs (Kubernetes Pods) for the Data Manager service.

Prerequisites: -

-   Python (ideally 3.9.x)
-   Docker
-   A kubernetes config file

## Building the operator (local development)
The operator container, residing in the `operator` directory,
is automatically built and pushed to Docker Hub using GitHub Actions.

You can build the image yourself using docker-compose.
The following will build an operator image with the tag `1.0.0-alpha.1`: -

    $ export IMAGE_TAG=1.0.0-alpha.1
    $ docker-compose build

## Deploying into the Data Manager API
We use [Ansible] 4 and community modules in [Ansible Galaxy] as the deployment
mechanism, using the `operator` Ansible role in this repository and a
Kubernetes config (KUBECONFIG). All of this is done via a suitable Python
environment using the requirements in the root of the project...

    $ python -m venv ~/.venv/data-manager-job-operator
    $ source ~/.venv/data-manager-job-operator/bin/activate
    $ pip install --upgrade pip
    $ pip install -r requirements.txt
    $ ansible-galaxy install -r requirements.yaml

Now, create a parameter file (i.e. `parameters.yaml`) based on the project's
`example-parameters.yaml`, setting values for the operator that match your
needs. Then deploy, using Ansible, from the root of the project: -

    $ export PARAMS=parameters
    $ ansible-playbook -e @${PARAMS}.yaml site.yaml

To remove the operator (assuming there are no operator-derived instances)...

    $ ansible-playbook -e @${PARAMS}.yaml -e jo_state=absent site.yaml

>   The current Data Manager API assumes that once an Application (operator)
    has been installed it is not removed. So, removing the operator here
    is described simply to illustrate a 'clean-up' - you would not
    normally remove an Application operator in a production environment.

The staging and production sites have parameter vaults. To deploy there
you will need the vault password: -

    $ export PARAMS=staging-parameters
    $ ansible-playbook -e @${PARAMS}.yaml.vault --ask-vault-password site.yaml

---

[ansible]: https://pypi.org/project/ansible/
[ansible galaxy]: https://galaxy.ansible.com
[kopf]: https://pypi.org/project/kopf/
[kubernetes]: https://pypi.org/project/kubernetes/
[operator]: https://kubernetes.io/docs/concepts/extend-kubernetes/operator/

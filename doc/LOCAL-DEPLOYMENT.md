# Local deployment
Notes for deployment to a local cluster, like [minikube] or [Docker Desktop].

> It is assumed that you have a local Kubernetes cluster, built using
  minikube or Docker Desktop, **AND** you have already deployed the Data Manager
  the cluster.

You will now need: -

- This repository (but you'll have that already)
- Python 3
- [lens]

## Create an environment for the Ansible playbooks
You will need a Python virtual environment for ansible playbook execution.
You may be running playbooks from several repositories, so you can re-use
this one.

Idally, you should use Python 3. Create an environment from the root
of the repository clone: -

    python -m venv venv

    source venv/bin/activate
    pip install -r requirements.txt

## Deploy the Job Operator
From the root of your clone of the `data-manager-job-operator` repository,
and within the Ansible environment you created in the previous step,
copy the `local-parameters.yaml` file to `parameters.yaml` and change the variables
to suit your local cluster.

>   You will need a KUBECONFIG file, and refer to it using the `jo_kubeconfig`
    variable and make sure `kubectl get no` returns nodes you expect.

Now deploy the Job Operator: -

    ansible-playbook site.yaml -e @parameters.yaml

The operator should deploy to the namespace `data-manager-job-operator`.
Run: -

    kubectl get po -n data-manager-job-operator

To see something like this...

    NAME                            READY   STATUS    RESTARTS   AGE
    job-operator-5c9b4bdb77-hzjh7   1/1     Running   0          21s

---

[docker desktop]: https://www.docker.com/products/docker-desktop/
[minikube]: https://minikube.sigs.k8s.io/docs/start/

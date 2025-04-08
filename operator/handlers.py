"""A kopf handler for the DataManagerJob CRD."""

import os
import shlex
import time
from typing import Any, Dict, List, Optional

import logging
import kopf
import kubernetes

# Configuration of underlying API requests.
#
# Request timeout (from Python Kubernetes API)
#   If one number provided, it will be total request
#   timeout. It can also be a pair (tuple) of
#   (connection, read) timeouts.
_REQUEST_TIMEOUT = (30, 20)

# Pod pre-delete delay (seconds).
# A fixed period of time the 'job_event' method waits
# after deciding to delete the Pod before actually deleting it.
# This delay gives the Data Manager log-watcher an opportunity to collect
# any remaining log events.
_POD_PRE_DELETE_DELAY_S: int = int(os.environ.get("JO_POD_PRE_DELETE_DELAY_S", "5"))

# Job Pod node selection
_POD_NODE_SELECTOR_KEY: str = os.environ.get(
    "JO_POD_NODE_SELECTOR_KEY", "informaticsmatters.com/purpose-worker"
)
_POD_NODE_SELECTOR_VALUE: str = os.environ.get("JO_POD_NODE_SELECTOR_VALUE", "yes")

# Default queue size?
_NF_EXECUTOR_QUEUE_SIZE: int = int(os.environ.get("JO_NF_EXECUTOR_QUEUE_SIZE", "100"))
# Enable ANSI stdout log?
# Unless 'true' it's 'false'
_NF_ANSI_LOG: str = os.environ.get("JO_NF_ANSI_LOG", "false")

# Apply Pod Priority class?
# Any value results in setting the Pod's Priority Class
_APPLY_POD_PRIORITY_CLASS: Optional[str] = os.environ.get("JO_APPLY_POD_PRIORITY_CLASS")
# If set and JO_APPLY_POD_PRIORITY_CLASS is set
# this value will be used if now alternative is available.
_DEFAULT_POD_PRIORITY_CLASS: str = os.environ.get(
    "JO_DEFAULT_POD_PRIORITY_CLASS", "im-worker-medium"
)

# Default CPU and MEM using Kubernetes units
# (applies to default requests and limits)
_POD_DEFAULT_CPU: str = os.environ.get("JO_POD_DEFAULT_CPU", "1")
_POD_DEFAULT_MEMORY: str = os.environ.get("JO_POD_DEFAULT_MEMORY", "1Gi")

# The Service Account to attach the Pods to.
# By default it's the DM's built-in app-based service account
_POD_SA: str = os.environ.get("JO_POD_SA", "data-manager-app")

# Some (key) default variables...
default_cpu: str = _POD_DEFAULT_CPU
default_memory: str = _POD_DEFAULT_MEMORY
default_project_mount: str = "/project"
default_project_claim_name: str = "project"
default_user_id: int = 1001
default_group_id: int = 1001


# The Nextflow kubernetes config file.
# A ConfigMap written into the working directory, or root.
nextflow_config: str = """
process {
  pod = [ %(extra_pod_settings)s
          [nodeSelector: '%(selector_key)s=%(selector_value)s'],
          [label: 'data-manager.informaticsmatters.com/instance-id',
           value: '%(name)s'] ]
}
executor {
  name = 'k8s'
  queueSize = %(executor_queue_size)s
}
k8s {
  computeResourceType = 'Job'
  serviceAccount = '%(sa)s'
  securityContext: [runAsUser: %(user)s, runAsGroup: %(group)s, fsGroup: 0]
  storageClaimName = '%(claim_name)s'
  storageMountPath = '%(project_mount)s'
  storageSubPath = '%(project_id)s'
  workDir = '%(project_mount)s/.%(name)s/work'
}
"""


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    """The operator startup handler."""
    # Here we adjust the logging level
    settings.posting.level = logging.INFO

    # Attempt to protect ourselves from missing watch events.
    # See https://github.com/nolar/kopf/issues/698
    # Added in an attempt to prevent the operator "falling silent"
    settings.watching.client_timeout = 3 * 60
    settings.watching.connect_timeout = 1 * 60
    settings.watching.server_timeout = 10 * 60

    logging.info("Startup _NF_EXECUTOR_QUEUE_SIZE=%s", _NF_EXECUTOR_QUEUE_SIZE)
    logging.info("Startup _POD_DEFAULT_CPU=%s", _POD_DEFAULT_CPU)
    logging.info("Startup _POD_DEFAULT_MEMORY=%s", _POD_DEFAULT_MEMORY)
    logging.info("Startup _POD_NODE_SELECTOR_KEY=%s", _POD_NODE_SELECTOR_KEY)
    logging.info("Startup _POD_NODE_SELECTOR_VALUE=%s", _POD_NODE_SELECTOR_VALUE)
    logging.info("Startup _POD_PRE_DELETE_DELAY_S=%s", _POD_PRE_DELETE_DELAY_S)
    logging.info("Startup _POD_SA=%s", _POD_SA)
    if _APPLY_POD_PRIORITY_CLASS:
        logging.info(
            "Startup _DEFAULT_POD_PRIORITY_CLASS=%s", _DEFAULT_POD_PRIORITY_CLASS
        )


@kopf.on.create("datamanagerjobs")
def create(name, namespace, spec, **_):
    """Handler for CRD create events.
    Here we construct the required Kubernetes objects,
    adopting them in kopf before using the corresponding Kubernetes API
    to create them.

    We handle errors typically raising 'kopf.PermanentError' to prevent
    Kubernetes constantly calling back for a given create.
    """

    logging.info("Starting create (name=%s namespace=%s)...", name, namespace)
    logging.info("spec=%s (name=%s)", spec, name)

    # A PermanentError is raised for any 'do not try this again' problems.
    # There are mandatory properties, that cannot have defaults.
    # The name is the Data Manager instance ID (UUID)
    if not name:
        raise kopf.PermanentError("The object must have a name")
    if not namespace:
        raise kopf.PermanentError("The object must have a namespace")
    if not spec:
        raise kopf.PermanentError("The object must have a spec")

    # All Data-Manager provided material
    # will be namespaced under the 'imDataManager' property
    material: Dict[str, any] = spec.get("imDataManager", {})
    logging.info("material=%s (name=%s)", material, name)

    extras: Dict[str, any] = spec.get("imDataManagerExtras", {})
    logging.info("extras=%s (name=%s)", extras, name)

    image: str = material.get("image")
    if not image:
        msg = "image is not defined"
        logging.error(msg)
        raise kopf.PermanentError(msg)
    image_type: str = material.get("imageType")
    if not image_type:
        msg = "imageType is not defined"
        logging.error(msg)
        raise kopf.PermanentError(msg)
    command: str = material.get("command")
    if not command:
        msg = "command is not defined"
        logging.error(msg)
        raise kopf.PermanentError(msg)
    task_id: str = material.get("taskId")
    if not task_id:
        msg = "task_id is not defined"
        logging.error(msg)
        raise kopf.PermanentError(msg)
    project_id = material.get("project", {}).get("id")
    if not project_id:
        msg = "project_id is not defined"
        logging.error(msg)
        raise kopf.PermanentError(msg)
    working_directory = material.get("workingDirectory")
    if not working_directory:
        msg = "working_directory is not defined"
        logging.error(msg)
        raise kopf.PermanentError(msg)

    # Get the image tag - to automate the pull policy setting.
    # 'latest' and 'stable' images are always pulled,
    # all others are 'IfNotPresent'
    image_parts: List[str] = image.split(":")
    image_tag: str = "latest" if len(image_parts) == 1 else image_parts[1]
    image_pull_policy: str = (
        "Always" if image_tag.lower() in ["latest", "stable"] else "IfNotPresent"
    )

    # The Kubernetes image command is an array.
    # The supplied command is a string.
    # For now split using Python shlex module - i.e. one that honours quotes.
    # i.e. 'echo "Hello, world"' becomes ['echo', 'Hello, world']
    #
    # We must protect ourselves from split problems - which must be treated
    # as a PermanentError (sc-3437).
    try:
        command_items = shlex.split(command)
    except ValueError as ex:
        logging.error("Got ValueError trying to split the command (%s)", command)
        raise kopf.PermanentError(f"ValueError ({ex.status})")

    # Security options
    sc_run_as_user = material.get("securityContext", {}).get(
        "runAsUser", default_user_id
    )
    sc_run_as_group = material.get("securityContext", {}).get(
        "runAsGroup", default_group_id
    )

    # Are resource requests/limits provided?
    cpu_request: Any = (
        material.get("resources", {}).get("requests", {}).get("cpu", default_cpu)
    )
    memory_request: Any = (
        material.get("resources", {}).get("requests", {}).get("memory", default_memory)
    )
    cpu_limit: Any = (
        material.get("resources", {}).get("limits", {}).get("cpu", default_cpu)
    )
    memory_limit: Any = (
        material.get("resources", {}).get("limits", {}).get("memory", default_memory)
    )

    # The project mount
    project_mount = material.get("projectMount", default_project_mount)
    # The container working directory sub-path.
    # The sub-path is optional (and only used) if there's a working directory.
    working_sub_path = material.get("workingSubPath")
    # The project claim name and project-id.
    # The project ID must be provided.
    project_claim_name = material.get("project", {}).get(
        "claimName", default_project_claim_name
    )

    # Image pull secret?
    pull_secret: str = material.get("pullSecret", "")

    # ConfigMaps
    # ----------

    logging.info("Creating ConfigMap %s...", name)

    core_api = kubernetes.client.CoreV1Api()
    if image_type.lower() == "nextflow":
        # Do we need to provide extra Pod declaration settings?
        # For example, is there an image-pull-secret - if so
        # we add it to the nextflow.config to ensure all nextflow processes
        # have access to it.
        extra_pod_settings = ""
        if pull_secret:
            # If the main image has a pull-secret, put it in the config
            # so the other process pods in the nextflow workflow can use it.
            extra_pod_settings += f"[imagePullSecret: '{pull_secret}'],\n"
        if _APPLY_POD_PRIORITY_CLASS:
            extra_pod_settings += (
                f"[priorityClassName: '{_DEFAULT_POD_PRIORITY_CLASS}'],\n"
            )
        # Job environment variables?
        # Provided by the DM as an array of strings of the form '<KEY>=<VALUE>'
        # These are added to the NF config file's process/pod declaration
        # to they're available to the workers
        for environment in material.get("environment", []):
            key, value = environment.split("=")
            extra_pod_settings += f"[env: '{key}', value: '{value}'],\n"

        # A Nextflow Kubernetes configuration file
        # Written to the Job container as ${HOME}/nextflow.config
        configmap_vars = {
            "executor_queue_size": _NF_EXECUTOR_QUEUE_SIZE,
            "extra_pod_settings": extra_pod_settings,
            "claim_name": project_claim_name,
            "name": name,
            "project_id": project_id,
            "project_mount": project_mount,
            "sa": _POD_SA,
            "user": sc_run_as_user,
            "group": sc_run_as_group,
            "selector_key": _POD_NODE_SELECTOR_KEY,
            "selector_value": _POD_NODE_SELECTOR_VALUE,
        }
        configmap_dmk = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": f"{name}-nf-config", "labels": {"app": name}},
            "data": {"nextflow.config": nextflow_config % configmap_vars},
        }

        kopf.adopt(configmap_dmk)
        try:
            core_api.create_namespaced_config_map(
                namespace, configmap_dmk, _request_timeout=_REQUEST_TIMEOUT
            )
        except kubernetes.client.exceptions.ApiException as ex:
            logging.warning("Got ApiException creating DMK ConfigMap (%s)", ex)
            # Whatever has happened treat it as a 'PermanentError',
            # thus preventing the operator from constantly re-trying.
            raise kopf.PermanentError(f"ApiException ({ex.status})")

        logging.info("Created ConfigMap %s", name)

    # Any files to inject into the image?
    # If so they have a 'name', 'content' and 'origin'.
    # The name is expected to be a qualified path like '/usr/local/blob.txt'.
    # We create a ConfigMap for each.

    image_files: List[Dict[str, str]] = material.get("file", [])
    file_number: int = 0
    for image_file in image_files:
        file_number += 1
        file_name: str = os.path.basename(image_file["name"])
        cm_name: str = f"{name}-file-{file_number}"
        configmap_file = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": cm_name,
                "labels": {"app": name},
                "annotations": {"origin": image_file["origin"]},
            },
            "data": {file_name: image_file["content"]},
        }

        kopf.adopt(configmap_file)
        try:
            core_api.create_namespaced_config_map(
                namespace, configmap_file, _request_timeout=_REQUEST_TIMEOUT
            )
        except kubernetes.client.exceptions.ApiException as ex:
            logging.warning("Got ApiException creating File ConfigMap (%s)", ex)
            # Whatever has happened treat it as a 'PermanentError',
            # thus preventing the operator from constantly re-trying.
            raise kopf.PermanentError(f"ApiException ({ex.status})")

        logging.info("Created ConfigMap %s", cm_name)

    # Pod
    # ---

    logging.info("Creating Pod %s...", name)

    # Job working directory (including any sub-path).
    # We mount the nextflow config on this path.
    working_path = working_directory
    if working_sub_path:
        working_path += f"/{working_sub_path}"

    pod: Dict[str, Any] = {
        "kind": "Pod",
        "apiVersion": "v1",
        "metadata": {"name": name, "labels": {}},
        "spec": {
            "serviceAccountName": _POD_SA,
            "nodeSelector": {_POD_NODE_SELECTOR_KEY: _POD_NODE_SELECTOR_VALUE},
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": name,
                    "image": image,
                    "command": command_items,
                    "workingDir": working_path,
                    "imagePullPolicy": image_pull_policy,
                    "terminationMessagePolicy": "FallbackToLogsOnError",
                    "env": [
                        {
                            "name": "NXF_WORK",
                            "value": project_mount + "/." + name + "/work",
                        }
                    ],
                    "resources": {
                        "requests": {
                            "cpu": f"{cpu_request}",
                            "memory": f"{memory_request}",
                        },
                        "limits": {"cpu": f"{cpu_limit}", "memory": f"{memory_limit}"},
                    },
                    "volumeMounts": [
                        {
                            "name": "project",
                            "mountPath": project_mount,
                            "subPath": project_id,
                        },
                    ],
                }
            ],
            "securityContext": {
                "runAsUser": sc_run_as_user,
                "runAsGroup": sc_run_as_group,
                "fsGroup": 0,
            },
            "volumes": [
                {
                    "name": "project",
                    "persistentVolumeClaim": {"claimName": project_claim_name},
                },
            ],
        },
    }

    # Insert a pod priority class?
    if _APPLY_POD_PRIORITY_CLASS:
        pod["spec"]["priorityClassName"] = _DEFAULT_POD_PRIORITY_CLASS

    # Pull secret?
    if pull_secret:
        pod["spec"]["imagePullSecrets"] = [{"name": pull_secret}]

    # Additional labels?
    # Provided by the DM as an array of strings of the form '<KEY>=<VALUE>'
    for label in material.get("labels", []):
        key, value = label.split("=")
        pod["metadata"]["labels"][key] = value

    # Instructed to debug the Job?
    # Yes if the spec's debug is set.
    # If so we add a DEBUG label to the template,
    # which prevents our 'on.event' handler from deleting the Job or its Pod.
    if material.get("debug"):
        logging.warning(
            "spec.debug is set. The corresponding Pod"
            " will not be automatically deleted"
        )
        pod["metadata"]["labels"]["debug"] = "yes"

    # Job environment variables?
    # Provided by the DM as an array of strings of the form '<KEY>=<VALUE>'
    # These are always added to the Job Pod, regardless of image_type.
    for environment in material.get("environment", []):
        key, value = environment.split("=")
        pod["spec"]["containers"][0]["env"].append(
            {
                "name": f"{key}",
                "value": f"{value}",
            }
        )

    # If it's a nextflow image type
    # add the nextflow config to the Pod.
    if image_type.lower() == "nextflow":
        # Extend the 'volumes' list...
        pod["spec"]["volumes"].append(
            {"name": "nf-config", "configMap": {"name": f"{name}-nf-config"}}
        )
        # ...and the corresponding container mounts...
        pod["spec"]["containers"][0]["volumeMounts"].append(
            {
                "name": "nf-config",
                "mountPath": f"{working_path}/nextflow.config",
                "subPath": "nextflow.config",
            }
        )
        # ...and some environment variables...
        pod["spec"]["containers"][0]["env"].append(
            {
                "name": "NXF_ANSI_LOG",
                "value": f"{_NF_ANSI_LOG}",
            }
        )

    # Files?
    # If so add appropriate volumes and mounts
    # using the config map we'll have created earlier.
    file_number: int = 0
    for image_file in image_files:
        file_number += 1
        file_name: str = os.path.basename(image_file["name"])
        cm_name: str = f"{name}-file-{file_number}"
        # Extend the 'volumes' list...
        pod["spec"]["volumes"].append(
            {"name": f"file-{file_number}", "configMap": {"name": cm_name}}
        )
        # ...and the corresponding container mounts...
        pod["spec"]["containers"][0]["volumeMounts"].append(
            {
                "name": f"file-{file_number}",
                "mountPath": image_file["name"],
                "subPath": file_name,
            }
        )

    # Definition's complete - adopt it and create it.
    # Pods are part of the Core V1 API
    kopf.adopt(pod)
    api: kubernetes.client.CoreV1Api = kubernetes.client.CoreV1Api()
    try:
        api.create_namespaced_pod(
            body=pod, namespace=namespace, _request_timeout=_REQUEST_TIMEOUT
        )
    except kubernetes.client.exceptions.ApiException as ex:
        logging.warning("Got ApiException creating Pod (%s)", ex)
        # Whatever has happened treat it as a 'PermanentError',
        # thus preventing the operator from constantly re-trying.
        raise kopf.PermanentError(f"ApiException ({ex.status})")

    logging.info("Created Pod %s", name)


@kopf.on.event(
    "datamanagerjobs",
    labels={"data-manager.informaticsmatters.com/instance-is-job": "yes"},
)
def job_event(event, **_):
    """An event handler for Pods that we created -
    i.e. those whose 'instance-is-job' is 'yes'.

    It's here we're able to detect that the Pod's run is complete.
    When it is, we delete the Pod and the Pod's Job
    (it won't be done automatically by the Operator).
    """
    event_type: str = event["type"]
    logging.info("Handling event_type=%s", event_type)

    if event_type == "MODIFIED":
        pod: Dict[str, Any] = event["object"]
        pod_phase: str = pod["status"]["phase"]

        logging.info("Handling event type=%s pod_phase=%s...", event_type, pod_phase)

        if pod_phase in ["Succeeded", "Failed", "Completed"]:
            pod_name: str = pod["metadata"]["name"]
            logging.info("...for Pod %s", pod_name)

            # Ignore the event if it relates to a Pod
            # that's explicitly marked for debug.
            if "debug" in pod["metadata"]["labels"]:
                logging.warning(
                    'Not deleting Job "%s".'
                    " It is protected from deletion"
                    " as it has a debug label.",
                    pod_name,
                )
                return

            # Ok to delete if we get here...
            logging.info('Job "%s" has finished.', pod_name)
            if _POD_PRE_DELETE_DELAY_S > 0:
                logging.info(
                    'Deleting "%s" after a delay of %s seconds...',
                    pod_name,
                    _POD_PRE_DELETE_DELAY_S,
                )
                time.sleep(_POD_PRE_DELETE_DELAY_S)

            # Delete the Pod
            pod_namespace: str = pod["metadata"]["namespace"]
            logging.info('Deleting Pod "%s" (namespace=%s)...', pod_name, pod_namespace)

            core_api: kubernetes.client.CoreV1Api = kubernetes.client.CoreV1Api()
            try:
                core_api.delete_namespaced_pod(
                    pod_name, pod_namespace, _request_timeout=_REQUEST_TIMEOUT
                )
            except kubernetes.client.exceptions.ApiException as ex:
                logging.warning(
                    'ApiException (%s) deleting Pod "%s" (%s)',
                    ex.status,
                    pod_name,
                    ex.body,
                )

            # Delete the ConfigMap
            # This will fail for non-nextflow Pods
            # We need a better way to identify the resources we created
            cm_name = f"{pod_name}-nf-config"
            logging.info('Deleting ConfigMap "%s"...', cm_name)
            core_api: kubernetes.client.CoreV1Api = kubernetes.client.CoreV1Api()
            try:
                core_api.delete_namespaced_config_map(
                    cm_name, pod_namespace, _request_timeout=_REQUEST_TIMEOUT
                )
            except kubernetes.client.exceptions.ApiException as ex:
                logging.warning(
                    'ApiException (%s) deleting ConfigMap "%s" (%s)',
                    ex.status,
                    cm_name,
                    ex.body,
                )

            logging.info('Deleted "%s"', pod_name)

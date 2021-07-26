"""A kopf handler for the DataManagerJob CRD.
"""
import os
import shlex
import time
from typing import Any, Dict, List

import logging
import kopf
import kubernetes

# Pod pre-delete delay (seconds).
# A fixed period of time the 'job_event' method waits
# after deciding to delete the Pod before actually deleting it.
# This delay gives the Data Manager log-watcher an opportunity to collect
# any remaining log events.
_POD_PRE_DELETE_DELAY_S: int = int(os.environ.get('JO_POD_PRE_DELETE_DELAY_S', '5'))

# The application SA
SA = 'data-manager-app'

# Some (key) default variables...
default_cpu: str = '1'
default_memory: str = '1Gi'
default_project_mount: str = '/project'
default_project_claim_name: str = 'project'
default_user_id = 1001
default_group_id = 1001
default_fs_group = 1001


# The Nextflow kubernetes config file.
# A ConfigMap written into the directory '$HOME/data-manager.config'
nextflow_config = """
process {
  pod = [ [nodeSelector: 'informaticsmatters.com/purpose-worker=yes'],
          [label: 'data-manager.informaticsmatters.com/instance-id',
           value: '%(name)s'] ]
}
executor {
  name = 'k8s'
}
k8s {
  serviceAccount = '%(sa)s'
  runAsUser = %(sc_run_as_user)s
  storageClaimName = '%(claim_name)s'
  storageMountPath = '%(project_mount)s'
  storageSubPath = '%(project_id)s'
  workDir = '%(project_mount)s/.%(name)s/work'
}
"""


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    """The operator startup handler.
    """
    # Here we adjust the logging level
    settings.posting.level = logging.INFO

    logging.info('Startup _POD_PRE_DELETE_DELAY_S=%s', _POD_PRE_DELETE_DELAY_S)


@kopf.on.create('squonk.it', 'v1', 'datamanagerjobs')
def create(name, namespace, spec, **_):
    """Handler for CRD create events.
    Here we construct the required Kubernetes objects,
    adopting them in kopf before using the corresponding Kubernetes API
    to create them.

    We handle errors typically raising 'kopf.PermanentError' to prevent
    Kubernetes constantly calling back for a given create.
    """

    # A PermanentError is raised for any 'do not try this again' problems.
    # There are mandatory properties, that cannot have defaults.
    # The name is the Data Manager instance ID (UUID)
    if not name:
        raise kopf.PermanentError('The object must have a name')
    if not namespace:
        raise kopf.PermanentError('The object must have a namespace')
    if not spec:
        raise kopf.PermanentError('The object must have a spec')

    # All Data-Manager provided material
    # will be namespaced under the 'imDataManager' property
    material: Dict[str, any] = spec.get('imDataManager', {})

    image: str = material.get('image')
    if not image:
        raise kopf.PermanentError('image is not defined')
    command: str = material.get('command')
    if not command:
        raise kopf.PermanentError('command is not defined')
    task_id: str = material.get('taskId')
    if not task_id:
        raise kopf.PermanentError('taskId is not defined')
    project_id = material.get('project', {}).get('id')
    if not project_id:
        raise kopf.PermanentError('project.id is not defined')

    # Get the image tag - to automate the pull policy setting.
    # 'latest' and 'stable' images are always pulled,
    # all others are 'IfNotPresent'
    image_parts: List[str] = image.split(':')
    image_tag: str = 'latest' if len(image_parts) == 1 else image_parts[1]
    image_pull_policy: str = 'Always' if image_tag.lower() in ['latest', 'stable']\
        else 'IfNotPresent'

    # The Kubernetes image command is an array.
    # The supplied command is a string.
    # For now split using Python shlex module - i.e. one that honours quotes.
    # i.e. 'echo "Hello, world"' becomes ['echo', 'Hello, world']
    command_items = shlex.split(command)

    # Security options
    sc_run_as_user = material.get('securityContext', {})\
        .get('runAsUser', default_user_id)
    sc_run_as_group = material.get('securityContext', {})\
        .get('runAsGroup', default_group_id)

    # Are resource requests/limits provided?
    cpu_request: Any = material.get('resources', {})\
        .get('requests', {}).get("cpu", default_cpu)
    memory_request: Any = material.get('resources', {})\
        .get('requests', {}).get("memory", default_memory)
    cpu_limit: Any = material.get('resources', {})\
        .get('limits', {}).get('cpu', default_cpu)
    memory_limit: Any = material.get('resources', {})\
        .get('limits', {}).get('memory', default_memory)

    # The project mount
    project_mount = material.get('projectMount', default_project_mount)
    # The container working directory and sub-path,
    # The sub-path is expected (and only used) if there's a working directory.
    working_directory = material.get('workingDirectory')
    working_sub_path = material.get('workingSubPath')
    # The project claim name and project-id.
    # The project ID must be provided.
    project_claim_name = material.get('project', {})\
        .get('claimName', default_project_claim_name)

    # ConfigMaps
    # ----------

    # A Nextflow Kubernetes configuration file
    # Written to the Job container as ${HOME}/nextflow.config
    configmap_vars = {'claim_name': project_claim_name,
                      'name': name,
                      'project_id': project_id,
                      'project_mount': project_mount,
                      'sa': SA,
                      'sc_run_as_user': sc_run_as_user}
    configmap_dmk = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "nf-config-%s" % name,
            "labels": {
                "app": name
            }
        },
        "data": {
            "nextflow.config": nextflow_config % configmap_vars
        }
    }

    kopf.adopt(configmap_dmk)
    core_api = kubernetes.client.CoreV1Api()
    try:
        core_api.create_namespaced_config_map(namespace, configmap_dmk)
    except kubernetes.client.exceptions.ApiException as ex:
        # Whatever has happened treat it as a 'PermanentError',
        # thus preventing the operator from constantly re-trying.
        raise kopf.PermanentError(f'ApiException ({ex.status})')

    logging.info('Created ConfigMap %s', name)

    # Pod
    # ---

    pod: Dict[str, Any] = {
        'kind': 'Pod',
        'apiVersion': 'v1',
        'metadata': {
            'name': name,
            'labels': {}
        },
        'spec': {
            'serviceAccountName': SA,
            'restartPolicy': 'Never',
            'containers': [{
                'name': name,
                'image': image,
                'command': command_items,
                'imagePullPolicy': image_pull_policy,
                'terminationMessagePolicy': 'FallbackToLogsOnError',
                'env': [{
                    'name': 'NXF_WORK',
                    'value': project_mount + '/.' + name + '/work'
                }],
                'resources': {
                    'requests': {
                        'cpu': cpu_request,
                        'memory': memory_request
                    },
                    'limits': {
                        'cpu': cpu_limit,
                        'memory': memory_limit
                    }
                },
                'volumeMounts': [
                    {
                        'name': 'project',
                        'mountPath': project_mount,
                        'subPath': project_id
                    },
                    {
                        'name': 'nf-config',
                        'mountPath': '/code/nextflow.config',
                        'subPath': 'nextflow.config'
                    }
                ]
            }],
            'securityContext': {
                'runAsUser': sc_run_as_user,
                'runAsGroup': sc_run_as_group,
                'fsGroup': 0
            },
            'volumes': [
                {
                    'name': 'project',
                    'persistentVolumeClaim': {
                        'claimName': project_claim_name
                    },
                },
                {
                    "name": "nf-config",
                    "configMap": {
                        "name": "nf-config-%s" % name
                    }
                }
            ]
        }
    }

    # Additional labels?
    # Provided by the DM as an array of strings of the form '<KEY>=<VALUE>'
    for label in material.get('labels', []):
        key, value = label.split('=')
        pod['metadata']['labels'][key] = value

    # Optional Job working directory and sub-path
    if working_directory:
        path = working_directory
        if working_sub_path:
            path = os.path.join(working_directory, working_sub_path)
        pod['spec']['containers'][0]['workingDir'] = path
        logging.warning('spec.workingDirectory is set.'
                        ' Setting workingDir to %s', path)

    # Instructed to debug the Job?
    # Yes if the spec's debug is set.
    # If so we add a DEBUG label to the template,
    # which prevents our 'on.event' handler from deleting the Job or its Pod.
    if material.get('debug'):
        logging.warning('spec.debug is set. The corresponding Pod'
                        ' will not be automatically deleted')
        pod['metadata']['labels']['debug'] = 'yes'

    # Definition's complete - adopt it.
    kopf.adopt(pod)

    # Noe create it - Pods are part of the Core V1 API
    api: kubernetes.client.CoreV1Api = kubernetes.client.CoreV1Api()
    try:
        api.create_namespaced_pod(body=pod,
                                  namespace=namespace)
    except kubernetes.client.exceptions.ApiException as ex:
        # Whatever has happened treat it as a 'PermanentError',
        # thus preventing the operator from constantly re-trying.
        raise kopf.PermanentError(f'ApiException ({ex.status})')

    logging.info('Created Pod %s',  name)


@kopf.on.event('', 'v1', 'pods',
               labels={'data-manager.informaticsmatters.com/purpose': 'INSTANCE'})
def job_event(event, **_):
    """An event handler for Pods that we created -
    i.e. those whose 'purpose' is 'JOB'.

    It's here we're able to detect that the Pod's run is complete.
    When it is, we delete the Pod and the Pod's Job
    (it won't be done automatically by the Operator).
    """
    event_type: str = event['type']
    logging.info('Handling event_type=%s', event_type)

    if event_type == 'MODIFIED':
        pod: Dict[str, Any] = event['object']
        pod_phase: str = pod['status']['phase']

        logging.info('Handling event type=%s pod_phase=%s...',
                     event_type, pod_phase)

        if pod_phase in ['Succeeded', 'Failed', 'Completed']:

            pod_name: str = pod['metadata']['name']
            logging.info('...for Pod %s', pod_name)

            # Ignore the event if it relates to a Pod
            # that's explicitly marked for debug.
            if 'debug' in pod['metadata']['labels']:
                logging.warning('Not deleting Job "%s".'
                                ' It is protected from deletion'
                                ' as it has a debug label.', pod_name)
                return

            # Ok to delete if we get here...
            logging.info('Job "%s" has finished.', pod_name)
            if _POD_PRE_DELETE_DELAY_S > 0:
                logging.info('Deleting "%s"'
                             ' after a delay of %s'
                             ' seconds...', pod_name, _POD_PRE_DELETE_DELAY_S)
                time.sleep(_POD_PRE_DELETE_DELAY_S)

            # Delete the Pod
            pod_namespace: str = pod['metadata']['namespace']
            logging.info('Deleting Pod "%s" (namespace=%s)...',
                         pod_name, pod_namespace)

            core_api: kubernetes.client.CoreV1Api = kubernetes.client.CoreV1Api()
            try:
                core_api.delete_namespaced_pod(pod_name, pod_namespace)
            except kubernetes.client.exceptions.ApiException as ex:
                logging.warning('ApiException (%s) deleting Pod "%s" (%s)',
                                ex.status, pod_name, ex.body)

            # Delete the ConfigMap
            cm_name = f'nf-config-{pod_name}'
            logging.info('Deleting ConfigMap "%s"...', cm_name)
            core_api: kubernetes.client.CoreV1Api = kubernetes.client.CoreV1Api()
            try:
                core_api.delete_namespaced_config_map(cm_name, pod_namespace)
            except kubernetes.client.exceptions.ApiException as ex:
                logging.warning('ApiException (%s) deleting ConfigMap "%s" (%s)',
                                ex.status, cm_name, ex.body)

            logging.info('Deleted "%s"', pod_name)

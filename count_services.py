#!/usr/bin/env python3
"""Count unique service occurrences from a list, sorted descending."""

import sys
from collections import Counter

SERVICES = """guardduty/ec2-ice-canary
emr
alameda/dpps
bigmac/control-plane/cp-canary
aws-console-proxy
tcell
guardduty/uluru
dynamodb/brms
Asgard/asgard-ragnarok
ec2containerservice/ecs-evm
directconnect/bgpexpander
fargate-fmi/node-manager-e2e-tests
qt-platform
guardduty/metadata-service-v2
securityagent/hobbesfrontendservice
codebuild/operations
tools_experience
ec2containerservice/ecs-evm
centrifuge-batching-service
eks-cfs
fargate/cellular-e2e-tests
dynamodb/brms
bigmac/data-plane/myna
rds-ela
bigmac/data-plane/myna
elasticsearchservice/beaglerock
lambda/uluru-function
dlm
lambda/lambda-control-plane-service
elasticsearchservice/dataplane
codebuild/operations
sagemaker/role-proxy-service
hwmon/hwmontimberfs
fargate-e2e-tests
codedeploy
elasticsearchservice/configservice-staging
amazonlinux/amazon-linux-repository-infra
awsconfig/awsconfig-contributedrules
securityhub/levee-console
elb_console
codebuild/operations
secretsmanager/cloudformation
awsfluffy/executionregionbuildconfig
route53firewall-gamma
sts
tangerinebox/tangerinebox-resiliency
ec2launchreservations/ec2launchreservations-cr-sharing
jedi/router-service
elasticsearchservice/sharedinfrastructure
nl-syslog/nl-syslog-sandbox
guardduty/agent
aws_console_navigation_widget
certificatemanager/aura-services/bifrost
guardduty/ec2-ice-canary
Asgard/asgard-ragnarok
consolehome
fargate/cellular-e2e-tests
ALL
ALL
bigmac/control-plane/cp-canary
searchservices-groot
cognitoidp/cognito-upm
lambda/lambda-control-plane-service
iam-policy-simulator
msk
redfort/redfort-proxy-retrieval-api
fargate-e2e-tests
access-analyzer-policy-validation
awsfluffy
securityhub/levee-console
dynamodb/brms
securityagent/awshobbesdataservice
tcell
awsconfig/awsconfig-contributedrules
bigmac/control-plane/lb-manager
apigateway/dataplane-v2
centrifuge-batching-service
centrifuge-batching-service
msk
titan/PrivateLink/titan-domain-verification
dynamodb/rr
elb/elb_ccs
ALL
route53profiles
mcm/mcm-nextgen-website
cryo-lag-vault
ALL
awsssopuppersservice
consolehome
tangerinebox/tangerinebox-resiliency
servicediscovery
sagemaker/role-proxy-service
glue/glue-jes-service
ec2containerregistry/ecr_lifecyclepolicy_prod
fargate-fmi/node-manager-e2e-tests
titan/PrivateLink/titan-service
elb_agw/agw_wfs
awsfluffy/executionregionbuildconfig
appsauthsamlruntimeservice
securityagent/awshobbesdataservice
EKS/eks-cfn-certauthority
Managed-SSH
cloudwatch/minions
elasticsearchservice/pacman
consolehome
redshift/adminworkflow
guardduty/documents-publishing
coda-pimms
ec2containerregistry/ecr_lifecyclepolicy_prod
awsconfig/configrules
elasticsearchservice/configservice-staging
bigmac/control-plane/lb-manager
rds.sql.server
elb/elb_ccs
ec2containerregistry
dlm
ec2containerservice/analytics
eice
EKS/eks-cfn-certauthority
directconnectv2/provisioningservice
elb/elb_cp/alb_target_composition_sync
access-analyzer-policy-validation
mcm/mcm-nextgen-website
fargate-metering
ec2containerservice/ccms
Cryo/s3backup
elasticsearchservice/legosservice
PokedexRuntime
redfort/redfort-proxy-retrieval-api
elb/elb_cp/alb_target_composition_sync
guardduty/agent
aws_console_navigation_widget
elasticsearchservice/symphony-oss
elasticsearchservice/sharedinfrastructure
EKS/fleetpatch
cognitoidp/cognito-upm
elb_agw/agw_wfs
supportauthz
nl-syslog/nl-syslog-sandbox
quilt
vmimportexport
Cryo/storage
glue/glue-huron-service
cryo-lag-vault
guardduty/metadata-service-v2
eks-cfs
sns
searchservices-groot
secretsmanager
sagemaker/repositoryservice
EKS/eks-cfn-certauthority
qbs/unstructured-datasets
secretsmanager
Managed-SSH
iam-policy-simulator
EKS/fleetpatch
qt-platform
elasticsearchservice/symphony-oss
redshift/databaseengine
guardduty/metadata-service-v2
EKS/eks-cfn-certauthority
glue/glue-jes-service
awsconfig/configrules
alameda/dpps
networkdevicediscoveryservice/networkdevicediscoveryservice-prod
redshift/databaseengine
ec2containerservice/analytics
directconnect/sluice
integrals/gateway/appconfig
glue/glue-huron-service
blackfootmoderndashboard
mcm/mcm-nextgen-website
guardduty/agent
centrifuge-batching-service
sts
integrals/gateway/appconfig
securityhub/levee-console
redshift/configservice
certificatemanager/aura-services/bifrost
elasticsearchservice/sharedinfrastructure
elb_console
access-analyzer-policy-validation
quilt
coda-pimms
elasticsearchservice/sharedinfrastructure
ecncontroller
ec2containerservice/analytics
elasticsearchservice/dataplane
emr
dynamodb/globaltables/gtmetadataservice
hwmon/hwmontimberfs
appsauthsamlruntimeservice
cryo-lag-vault
ec2containerservice/analytics
fargate-metering
dynamodb/globaltables/gtmetadataservice
autoscaling
emr
curtain
secretsmanager
Cryo/storage
lambda/uluru-function
kendra/pms
PokedexRuntime
vmimportexport
iam-policy-simulator
supportauthz
tangerinebox/tangerinebox-resiliency
ec2containerregistry
secretsmanager/cloudformation
datafeeds/awsingestionhubdataplane
rds.aurora.postgresql
qt-platform/gamma/transform-cp
awsssooidcservice
awsfluffy
qbs/spaces
guardduty/metadata-service-v2
elasticsearchservice/beaglerock
tangerinebox/tangerinebox-resiliency
qbs/spaces
airflow
tools_experience
sns
qbs/unstructured-datasets
ec2containerservice/edo
awsconfig/aggregators
apigateway
redshift/adminworkflow
kendra/pms
guardduty/ec2-ice-canary
codebuild/operations
wadi
awsconfig/aggregators
securityhub/levee-console
redshift/adminworkflow
cognitoidp/cognito-upm
networkdevicediscoveryservice/networkdevicediscoveryservice-prod
rds.mysql
redshift/configservice
ec2containerservice/ccms
autoscaling
route53profiles
elasticsearchservice/pacman
apigateway/dataplane-v2
netcollector-jti/netcollector-jti-prod
awsconfig/configrules
wadi
elasticsearchservice/beaglerock
datafeeds/awsingestionhubdataplane
securityagent/hobbesfrontendservice
guardduty/agent
Cryo/s3backup
iam-policy-simulator
directconnect/sluice
airflow
datafeeds/awsingestionhub
cognitoidp/cognito-upm
qbs/spaces
elasticsearchservice/legosservice
guardduty/documents-publishing
netcollector-jti/netcollector-jti-prod
dynamodb/brms
guardduty/ec2-ice-canary
consolehome
datafeeds/awsingestionhub
emr
organizations/policies/eped
ec2containerservice/edo
apigateway
sagemaker/repositoryservice
servicediscovery
awsfluffy
organizations/policies/eped
route53firewall-gamma
bigmac/control-plane/lb-manager
awsfluffy
secretsmanager/cloudformation
ec2launchreservations/ec2launchreservations-cr-sharing
rds.aurora.postgresql
fargate-e2e-tests
titan/PrivateLink/titan-service
cryo-lag-vault
dynamodb/rr
blackfootmoderndashboard
eice
cloudwatch/minions
aws-console-proxy
ec2containerservice/ecs-evm
rds-ela
rds.sql.server
mcm/mcm-nextgen-website
guardduty/uluru
elasticsearchservice/beaglerock
jedi/router-service
secretsmanager
secretsmanager/cloudformation
qt-platform/gamma/transform-cp
titan/PrivateLink/titan-domain-verification
directconnect/bgpexpander
rds.mysql
awsssopuppersservice
access-analyzer-policy-validation
coda-pimms
awsssooidcservice
awsconfig/configrules
qbs/spaces
fargate-e2e-tests
ec2containerservice/ecs-evm
curtain
amazonlinux/amazon-linux-repository-infra
redshift/adminworkflow
ecncontroller
bigmac/control-plane/lb-manager
directconnectv2/provisioningservice
codedeploy
coda-pimms"""


def count_services(text: str) -> list[tuple[str, int]]:
    """Parse service list, count occurrences, return sorted descending."""
    services = [line.strip() for line in text.strip().splitlines() if line.strip()]
    counts = Counter(services)
    return counts.most_common()


def main():
    # Allow piping in a custom list via -; otherwise use the embedded data
    if len(sys.argv) > 1 and sys.argv[1] == "-":
        text = sys.stdin.read()
    else:
        text = SERVICES

    results = count_services(text)

    total_entries = sum(c for _, c in results)
    unique_count = len(results)

    print(f"{'Service':<60} {'Count':>5}")
    print("-" * 66)
    for service, count in results:
        print(f"{service:<60} {count:>5}")
    print("-" * 66)
    print(f"{'Unique services:':<60} {unique_count:>5}")
    print(f"{'Total entries:':<60} {total_entries:>5}")


if __name__ == "__main__":
    main()

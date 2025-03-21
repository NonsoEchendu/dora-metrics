import os
import time
import logging
from datetime import datetime, timedelta
import requests
from prometheus_client import start_http_server, Gauge, Counter
import schedule
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# GitHub configuration
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPOSITORIES = json.loads(os.environ.get('GITHUB_REPOSITORIES', '[]'))

if not REPOSITORIES:
    # Fallback to legacy env vars for backward compatibility
    owner = os.environ.get('GITHUB_OWNER')
    repo = os.environ.get('GITHUB_REPO')
    if owner and repo:
        REPOSITORIES = [{"owner": owner, "repo": repo}]

HEADERS = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# Define Prometheus metrics
deployment_frequency = Gauge('dora_deployment_frequency', 'Deployments per day', ['repo'])
lead_time = Gauge('dora_lead_time_seconds', 'Lead time for changes in seconds', ['repo'])
change_failure_rate = Gauge('dora_change_failure_rate', 'Percentage of deployments that failed', ['repo'])
mttr = Gauge('dora_mean_time_to_restore_seconds', 'Mean time to restore service in seconds', ['repo'])

deployment_counter = Counter('dora_deployments_total', 'Total number of deployments', ['repo', 'status'])
incident_counter = Counter('dora_incidents_total', 'Total number of incidents', ['repo'])
recovery_time_sum = Counter('dora_recovery_time_seconds_sum', 'Sum of recovery times in seconds', ['repo'])
recovery_count = Counter('dora_recovery_count', 'Count of recoveries', ['repo'])

# Time window for metrics (last 30 days)
TIME_WINDOW_DAYS = 30

def paginate_github_api(url, params=None):
    """
    Helper function to handle GitHub API pagination and rate limiting
    Returns all items from all pages
    """
    if params is None:
        params = {}
    
    all_items = []
    page = 1
    per_page = 100
    
    while True:
        page_params = {**params, 'page': page, 'per_page': per_page}
        try:
            response = requests.get(url, headers=HEADERS, params=page_params, timeout=30)
            
            # Handle rate limiting
            if response.status_code == 403 and 'rate limit' in response.text.lower():
                reset_time = int(response.headers.get('X-RateLimit-Reset', 0))
                wait_time = max(1, reset_time - int(time.time()) + 5)
                logger.warning(f"Rate limit hit. Waiting {wait_time} seconds before retrying.")
                time.sleep(wait_time)
                continue
                
            # Handle other errors
            if response.status_code != 200:
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                return all_items
                
            # Process results
            items = response.json()
            
            # Handle different response formats
            if isinstance(items, dict) and 'items' in items:
                page_items = items['items']
                total_count = items.get('total_count', 0)
            elif isinstance(items, dict) and any(k in items for k in ['workflow_runs', 'commits']):
                for key in ['workflow_runs', 'commits']:
                    if key in items:
                        page_items = items[key]
                        total_count = items.get('total_count', 0)
                        break
                else:
                    page_items = []
                    total_count = 0
            elif isinstance(items, list):
                page_items = items
                total_count = len(items)
            else:
                page_items = []
                total_count = 0
                
            logger.debug(f"Retrieved {len(page_items)} items from page {page} (total: {total_count})")
            
            if not page_items:
                break
                
            all_items.extend(page_items)
            
            # Check if we've reached the last page
            if len(page_items) < per_page:
                break
                
            page += 1
            
        except Exception as e:
            logger.error(f"Error during API pagination: {str(e)}")
            break
            
    return all_items

def get_github_workflows(owner, repo):
    """Get GitHub workflow runs for a repository within time window"""
    logger.info(f"Fetching workflow runs for {owner}/{repo}")
    
    # Calculate time window
    now = datetime.now()
    cutoff_date = now - timedelta(days=TIME_WINDOW_DAYS)
    cutoff_date_str = cutoff_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    url = f'https://api.github.com/repos/{owner}/{repo}/actions/runs'
    
    try:
        # Get all workflow runs
        all_workflow_runs = paginate_github_api(url)
        
        # Filter by time window
        recent_workflow_runs = []
        for run in all_workflow_runs:
            try:
                run_date = datetime.strptime(run['created_at'], '%Y-%m-%dT%H:%M:%SZ')
                if run_date >= cutoff_date:
                    recent_workflow_runs.append(run)
                elif recent_workflow_runs:  # If we've already added some and now finding older ones, we can stop
                    break
            except (KeyError, ValueError) as e:
                logger.warning(f"Error processing workflow run date: {str(e)}")
                continue
        
        logger.info(f"Retrieved {len(recent_workflow_runs)} workflow runs for {owner}/{repo} within last {TIME_WINDOW_DAYS} days")
        
        # Log workflow types to help debugging
        workflow_names = {}
        for run in recent_workflow_runs:
            name = run.get('name', 'Unknown')
            workflow_names[name] = workflow_names.get(name, 0) + 1
            
        logger.info(f"Workflow types found: {json.dumps(workflow_names, indent=2)}")
        
        return recent_workflow_runs
        
    except Exception as e:
        logger.error(f"Failed to fetch workflow runs for {owner}/{repo}: {str(e)}")
        return []

def get_github_commits(owner, repo):
    """Get GitHub commits for a repository within time window"""
    logger.info(f"Fetching commits for {owner}/{repo}")
    
    # Calculate time window
    now = datetime.now()
    cutoff_date = now - timedelta(days=TIME_WINDOW_DAYS)
    cutoff_date_str = cutoff_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    url = f'https://api.github.com/repos/{owner}/{repo}/commits'
    params = {'since': cutoff_date_str}
    
    try:
        commits = paginate_github_api(url, params)
        logger.info(f"Retrieved {len(commits)} commits for {owner}/{repo} since {cutoff_date_str}")
        return commits
    except Exception as e:
        logger.error(f"Failed to fetch commits for {owner}/{repo}: {str(e)}")
        return []

def is_deployment_workflow(workflow_run):
    """
    Identify if a workflow run is a deployment workflow
    Using multiple indicators to catch different naming conventions
    """
    # Extract relevant information
    name = workflow_run.get('name', '').lower()
    path = workflow_run.get('path', '').lower()
    workflow_file = workflow_run.get('workflow_file', {})
    if isinstance(workflow_file, dict):
        file_name = workflow_file.get('name', '').lower()
    else:
        file_name = str(workflow_file).lower()
    
    # List of common deployment indicators
    deployment_indicators = [
        'deploy', 'deployment', 'release', 'publish', 'cd', 
        'continuous delivery', 'continuous deployment',
        'promote', 'provision', 'rollout', 'deploy-to', 
        'deploy_to', 'production', 'staging', 'prod', 
        'push-to', 'push_to', 'delivery', 'build-and-deploy'
    ]
    
    # Check workflow name
    for indicator in deployment_indicators:
        if indicator in name:
            return True
            
    # Check workflow path
    if path and any(ind in path for ind in deployment_indicators):
        return True
        
    # Check workflow file name
    if file_name and any(ind in file_name for ind in deployment_indicators):
        return True
        
    # Also check for explicit workflow events that suggest deployment
    if 'event' in workflow_run and workflow_run['event'] in ['deployment', 'release']:
        return True
        
    return False

def calculate_deployment_frequency(workflow_runs, repo_label):
    """Calculate deployment frequency (deployments per day)"""
    # Identify deployment workflows
    deployment_runs = [run for run in workflow_runs if is_deployment_workflow(run)]
    
    # Log identified deployment runs
    logger.info(f"Identified {len(deployment_runs)} deployment workflows out of {len(workflow_runs)} total workflows")
    
    if deployment_runs:
        sample_size = min(3, len(deployment_runs))
        logger.info(f"Sample deployment workflows:")
        for i in range(sample_size):
            run = deployment_runs[i]
            logger.info(f"  - {run.get('name')} ({run.get('created_at')}, status: {run.get('conclusion')})")
    
    # Count successful and failed deployments
    successful_deployments = [run for run in deployment_runs if run.get('conclusion') == 'success']
    failed_deployments = [run for run in deployment_runs if run.get('conclusion') == 'failure']
    
    # Set counter values (not incrementing to avoid duplication)
    try:
        deployment_counter.labels(repo=repo_label, status="success")._value.set(len(successful_deployments))
        deployment_counter.labels(repo=repo_label, status="failure")._value.set(len(failed_deployments))
    except AttributeError:
        # Fallback method if the above doesn't work
        logger.warning("Using alternative method to set counter values")
        # Clear previous values
        deployment_counter.labels(repo=repo_label, status="success")._value.inc(-deployment_counter.labels(repo=repo_label, status="success")._value.get())
        deployment_counter.labels(repo=repo_label, status="failure")._value.inc(-deployment_counter.labels(repo=repo_label, status="failure")._value.get())
        # Set new values
        deployment_counter.labels(repo=repo_label, status="success")._value.inc(len(successful_deployments))
        deployment_counter.labels(repo=repo_label, status="failure")._value.inc(len(failed_deployments))
    
    # Calculate deployments per day
    total_deployments = len(deployment_runs)
    deployments_per_day = total_deployments / TIME_WINDOW_DAYS if TIME_WINDOW_DAYS > 0 else 0
    
    logger.info(f"Deployment frequency: {deployments_per_day:.4f} deployments/day ({total_deployments} deployments in {TIME_WINDOW_DAYS} days)")
    
    return deployments_per_day

def calculate_lead_time(workflow_runs, commits, repo_label):
    """Calculate lead time for changes (time from commit to deployment)"""
    # Find successful deployment runs
    deployment_runs = [
        run for run in workflow_runs 
        if is_deployment_workflow(run) and run.get('conclusion') == 'success'
    ]
    
    logger.info(f"Calculating lead time using {len(deployment_runs)} successful deployments")
    
    lead_times = []
    processed_commits = 0
    
    for run in deployment_runs:
        try:
            deployment_time = datetime.strptime(run['created_at'], '%Y-%m-%dT%H:%M:%SZ')
            
            # Get the associated commit
            head_sha = run.get('head_sha')
            if not head_sha:
                continue
                
            # Try to find the commit in our list
            commit_info = None
            for commit in commits:
                if commit['sha'] == head_sha:
                    commit_info = commit
                    break
            
            if not commit_info:
                # If not found in our list, fetch it directly
                try:
                    owner, repo = repo_label.split('/')
                    url = f'https://api.github.com/repos/{owner}/{repo}/commits/{head_sha}'
                    response = requests.get(url, headers=HEADERS, timeout=30)
                    if response.status_code == 200:
                        commit_info = response.json()
                except Exception as e:
                    logger.warning(f"Error fetching commit {head_sha}: {str(e)}")
            
            if commit_info:
                processed_commits += 1
                commit_time = datetime.strptime(
                    commit_info['commit']['author']['date'], 
                    '%Y-%m-%dT%H:%M:%SZ'
                )
                lead_time_seconds = (deployment_time - commit_time).total_seconds()
                if lead_time_seconds > 0:  # Only consider positive lead times
                    lead_times.append(lead_time_seconds)
                    logger.debug(f"Lead time for commit {head_sha}: {lead_time_seconds/3600:.2f} hours")
        
        except Exception as e:
            logger.warning(f"Error processing lead time for run {run.get('id')}: {str(e)}")
    
    logger.info(f"Processed {processed_commits} commits for lead time calculation")
    
    avg_lead_time = sum(lead_times) / len(lead_times) if lead_times else 0
    logger.info(f"Average lead time: {avg_lead_time/3600:.2f} hours (based on {len(lead_times)} data points)")
    
    return avg_lead_time

def calculate_change_failure_rate(workflow_runs):
    """Calculate change failure rate (percentage of deployments that failed)"""
    # Get all deployment runs with success or failure conclusion
    deployment_runs = [
        run for run in workflow_runs 
        if is_deployment_workflow(run) and run.get('conclusion') in ['success', 'failure']
    ]
    
    total_deployments = len(deployment_runs)
    failed_deployments = len([run for run in deployment_runs if run.get('conclusion') == 'failure'])
    
    if total_deployments > 0:
        failure_rate = (failed_deployments / total_deployments) * 100
    else:
        failure_rate = 0
        
    logger.info(f"Change failure rate: {failure_rate:.2f}% ({failed_deployments} failures out of {total_deployments} deployments)")
    
    return failure_rate

def calculate_mttr(workflow_runs, repo_label):
    """
    Calculate mean time to restore service 
    (time between a failed deployment and the next successful one)
    """
    # Sort deployment runs by time
    deployment_runs = sorted(
        [run for run in workflow_runs if is_deployment_workflow(run) and run.get('conclusion') in ['success', 'failure']],
        key=lambda x: datetime.strptime(x['created_at'], '%Y-%m-%dT%H:%M:%SZ')
    )
    
    logger.info(f"Calculating MTTR using {len(deployment_runs)} deployment runs")
    
    restore_times = []
    failure_time = None
    total_restore_time = 0
    
    for run in deployment_runs:
        try:
            current_time = datetime.strptime(run['created_at'], '%Y-%m-%dT%H:%M:%SZ')
            
            if run.get('conclusion') == 'failure' and failure_time is None:
                failure_time = current_time
                logger.debug(f"Failure detected at {failure_time.isoformat()}")
                
            elif run.get('conclusion') == 'success' and failure_time is not None:
                restore_time = (current_time - failure_time).total_seconds()
                restore_times.append(restore_time)
                total_restore_time += restore_time
                logger.debug(f"Restore detected after {restore_time/3600:.2f} hours")
                failure_time = None
                
        except Exception as e:
            logger.warning(f"Error processing MTTR data point: {str(e)}")
    
    # Update the MTTR metrics
    recovery_count_value = len(restore_times)
    
    try:
        if recovery_count_value > 0:
            recovery_time_sum.labels(repo=repo_label)._value.set(total_restore_time)
            recovery_count.labels(repo=repo_label)._value.set(recovery_count_value)
    except AttributeError:
        # Fallback method
        if recovery_count_value > 0:
            # Clear previous values
            recovery_time_sum.labels(repo=repo_label)._value.inc(-recovery_time_sum.labels(repo=repo_label)._value.get())
            recovery_count.labels(repo=repo_label)._value.inc(-recovery_count.labels(repo=repo_label)._value.get())
            # Set new values
            recovery_time_sum.labels(repo=repo_label)._value.inc(total_restore_time)
            recovery_count.labels(repo=repo_label)._value.inc(recovery_count_value)
    
    avg_restore_time = total_restore_time / recovery_count_value if recovery_count_value > 0 else 0
    
    logger.info(f"MTTR: {avg_restore_time/3600:.2f} hours (based on {recovery_count_value} recoveries)")
    
    return avg_restore_time

def update_metrics_for_repo(owner, repo):
    """Update DORA metrics for a specific repository"""
    repo_label = f"{owner}/{repo}"
    logger.info(f"========== Updating DORA metrics for {repo_label} ==========")
    
    try:
        # Get workflow runs within time window
        workflow_runs = get_github_workflows(owner, repo)
        if not workflow_runs:
            logger.warning(f"No workflow runs found for {repo_label}. Skipping this repository.")
            return
        
        # Get commits within time window
        commits = get_github_commits(owner, repo)
        if not commits:
            logger.warning(f"No commits found for {repo_label}. Some metrics may be incomplete.")
        
        # Calculate and update metrics
        df = calculate_deployment_frequency(workflow_runs, repo_label)
        deployment_frequency.labels(repo=repo_label).set(df)
        
        lt = calculate_lead_time(workflow_runs, commits, repo_label)
        lead_time.labels(repo=repo_label).set(lt)
        
        cfr = calculate_change_failure_rate(workflow_runs)
        change_failure_rate.labels(repo=repo_label).set(cfr)
        
        mttr_value = calculate_mttr(workflow_runs, repo_label)
        mttr.labels(repo=repo_label).set(mttr_value)
        
        logger.info(f"=== Summary for {repo_label} ===")
        logger.info(f"Deployment Frequency: {df:.4f} deployments/day")
        logger.info(f"Lead Time: {lt/3600:.2f} hours")
        logger.info(f"Change Failure Rate: {cfr:.2f}%")
        logger.info(f"MTTR: {mttr_value/3600:.2f} hours")
        logger.info(f"========== Finished {repo_label} ==========\n")
        
    except Exception as e:
        logger.error(f"Error updating metrics for {repo_label}: {str(e)}", exc_info=True)

def update_metrics():
    """Update all DORA metrics for all repositories"""
    logger.info(f"====================================================")
    logger.info(f"Starting metrics update for {len(REPOSITORIES)} repositories...")
    logger.info(f"====================================================")
    
    start_time = time.time()
    
    for repo_config in REPOSITORIES:
        owner = repo_config.get('owner')
        repo = repo_config.get('repo')
        
        if owner and repo:
            update_metrics_for_repo(owner, repo)
        else:
            logger.warning(f"Skipping invalid repository config: {repo_config}")
    
    elapsed_time = time.time() - start_time
    logger.info(f"Metrics update completed in {elapsed_time:.2f} seconds")

def check_github_access():
    """Check if GitHub token is valid and has required permissions"""
    logger.info("Checking GitHub API access...")
    
    try:
        response = requests.get('https://api.github.com/user', headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            user_data = response.json()
            logger.info(f"GitHub access confirmed for user: {user_data.get('login')}")
            return True
        else:
            logger.error(f"GitHub API access check failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error checking GitHub access: {str(e)}")
        return False

def main():
    """Main function"""
    logger.info("Starting DORA metrics collector")
    
    # Check environment variables
    if not GITHUB_TOKEN:
        logger.error("Missing required GITHUB_TOKEN environment variable")
        logger.error("Please set this variable and restart the application")
        return
    
    if not REPOSITORIES:
        logger.error("No repositories configured. Please set GITHUB_REPOSITORIES environment variable")
        logger.error("Example: GITHUB_REPOSITORIES='[{\"owner\":\"username\",\"repo\":\"frontend\"},{\"owner\":\"username\",\"repo\":\"backend\"}]'")
        return
    
    # Check GitHub access
    if not check_github_access():
        logger.error("Failed to authenticate with GitHub. Please check your token and permissions.")
        return
    
    # Start Prometheus metrics server
    port = int(os.environ.get('PORT', 8000))
    start_http_server(port)
    logger.info(f"Prometheus metrics server started on port {port}")
    
    # Log repository information
    logger.info(f'Tracking {len(REPOSITORIES)} repositories:')
    for repo in REPOSITORIES:
        logger.info(f"  - {repo.get('owner', 'N/A')}/{repo.get('repo', 'N/A')}")
    
    # Initial update
    update_metrics()
    
    # Schedule regular updates
    update_interval = int(os.environ.get('UPDATE_INTERVAL_HOURS', 1))
    logger.info(f"Scheduling updates every {update_interval} hours")
    schedule.every(update_interval).hours.do(update_metrics)
    
    # Main loop
    logger.info("Entering main loop - press Ctrl+C to exit")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()

import subprocess
import sys

MAX_RETRIES = 5

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr

def deploy():
    print("Initializing Terraform...")
    code, out, err = run_cmd("terraform init")
    if code != 0:
        print(f"Error during terraform init:\n{err}")
        sys.exit(1)

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n--- Deployment Attempt {attempt}/{MAX_RETRIES} ---")
        
        # Attempt Terraform Apply
        code, out, err = run_cmd("terraform apply -auto-approve")
        
        if code == 0:
            print("\n[SUCCESS] Deployment completed successfully!")
            print(out)
            return
        
        print(f"[WARNING] Attempt {attempt} failed.")
        print(f"Error Output:\n{err}")
        
        if attempt < MAX_RETRIES:
            print("Tainting random_string suffix to generate a new unique suffix...")
            run_cmd("terraform taint random_string.suffix")
        else:
            print(f"\n[FATAL ERROR] All {MAX_RETRIES} attempts failed. Exiting with error.")
            sys.exit(1)

if __name__ == "__main__":
    deploy()

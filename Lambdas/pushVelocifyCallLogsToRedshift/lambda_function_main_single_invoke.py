import os
import json
import boto3
import botocore
import botocore.session as bc
from botocore.client import Config
import io
import csv
from datetime import datetime

# Initialize S3 client and Secrets Manager client
s3_client = boto3.client('s3')
secret_name = os.environ['SecretId']
session = boto3.session.Session()
region = session.region_name

# Secrets Manager client
client_secretsmanager = session.client(service_name='secretsmanager', region_name=region)
get_secret_value_response = client_secretsmanager.get_secret_value(SecretId=secret_name)
secret_arn = get_secret_value_response['ARN']
secret_json = json.loads(get_secret_value_response['SecretString'])
cluster_id = secret_json['dbClusterIdentifier']

# Redshift client
config = Config(connect_timeout=5, read_timeout=5)
client_redshift = session.client("redshift-data", config=config)

def lambda_handler(event, context):
    print(f"Entered lambda_handler: {event}")
    file_key = event['file_key']
    bucket_name = event['bucket_name']
    
    try:
        # Get the CSV file from S3
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        file_content = response['Body'].read().decode('utf-8')
        csv_file = io.StringIO(file_content)
        csv_reader = csv.DictReader(csv_file)
        
        for row in csv_reader:
            try:
                # Handle missing or optional fields
                call_id = row.get('Call Id') or 'NULL'
                lead_id = row.get('Lead Id') or 'NULL'
                origin = row.get('Origin') or 'NULL'
                time_field = row.get('Time') or 'NULL'
                call_duration = row.get('Call Duration (hrs:min:sec)', '0:00:00')
                talk_time = duration_to_seconds(call_duration) or 'NULL'
                
                # Wrap strings in single quotes, use NULL for missing values
                time_field = f"'{time_field}'" if time_field != 'NULL' else time_field
                call_id = f"'{call_id}'" if call_id != 'NULL' else call_id
                origin = f"'{origin}'" if origin != 'NULL' else origin

                # Construct SQL query to delete and insert
                delete_sql_query = f"""
                DELETE FROM public.Call WHERE Call_ID = {call_id};
                """
                insert_sql_query = f"""
                INSERT INTO public.Call (Call_ID, Call_Platform, Lead_ID, Call_Type, Date_Time, Talk_Time,Broker_ID)
                VALUES ({call_id}, 'Velocify', {lead_id}, {origin}, {time_field}, {talk_time},'c74f794c-c969-475a-9be4-d12d438a95d9');
                """
                
                # Execute delete query first
                execute_redshift_query(delete_sql_query)
                
                # Execute insert query
                execute_redshift_query(insert_sql_query)
            
            except Exception as row_error:
                print(f"Error processing row {row}: {str(row_error)}")
        
        return {
            'statusCode': 200,
            'body': 'Call logs processed successfully!'
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': f"Failed to process file: {str(e)}"
        }

def execute_redshift_query(query_str):
    """
    Execute a query in the Redshift cluster.
    """
    print(f"Executing query: {query_str}")
    try:
        result = client_redshift.execute_statement(
            Database='dev',
            SecretArn=secret_arn,
            Sql=query_str,
            ClusterIdentifier=cluster_id
        )
        print(f"Query executed successfully: {result}")
        return result

    except Exception as e:
        print(f"Error executing query: {str(e)}")
        raise

def duration_to_seconds(duration_str):
    """
    Convert a duration string in the format hrs:min:sec to seconds.
    """
    try:
        h, m, s = map(int, duration_str.split(":"))
        total_seconds = h * 3600 + m * 60 + s
        return total_seconds
    except ValueError:
        print(f"Invalid duration format: {duration_str}")
        return None

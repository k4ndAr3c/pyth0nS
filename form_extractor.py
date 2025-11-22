#!/usr/bin/env python3
"""
Form Field Extractor and Script Generator

This script fetches a webpage, extracts all form fields, and generates
a Python script that uses requests to submit data to those forms.
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import argparse
import sys
from typing import List, Dict, Any

class FormExtractor:
    def __init__(self, url: str):
        self.url = url
        self.session = requests.Session()
        # Add common headers to mimic a real browser
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def fetch_page(self) -> BeautifulSoup:
        """Fetch the webpage and return BeautifulSoup object"""
        try:
            response = self.session.get(self.url)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching page: {e}")
            sys.exit(1)
    
    def extract_forms(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract all forms and their fields from the page"""
        forms = []
        
        for i, form in enumerate(soup.find_all('form')):
            form_data = {
                'index': i,
                'action': form.get('action', ''),
                'method': form.get('method', 'get').lower(),
                'fields': [],
                'csrf_token': None
            }
            
            # Make action URL absolute
            if form_data['action']:
                form_data['action'] = urljoin(self.url, form_data['action'])
            else:
                form_data['action'] = self.url
            
            # Extract all input fields
            for field in form.find_all(['input', 'select', 'textarea']):
                field_info = self.extract_field_info(field)
                if field_info:
                    form_data['fields'].append(field_info)
                    
                    # Check for CSRF tokens
                    if field_info['name'] and any(token in field_info['name'].lower() 
                                                for token in ['csrf', 'token', '_token']):
                        form_data['csrf_token'] = field_info['name']
            
            forms.append(form_data)
        
        return forms
    
    def extract_field_info(self, field) -> Dict[str, Any]:
        """Extract information from a single form field"""
        field_type = field.name
        
        if field_type == 'input':
            input_type = field.get('type', 'text').lower()
            
            # Skip buttons and submits for data collection
            if input_type in ['button', 'submit', 'reset', 'image']:
                return None
            
            return {
                'name': field.get('name'),
                'id': field.get('id'),
                'type': input_type,
                'value': field.get('value', ''),
                'required': field.has_attr('required'),
                'placeholder': field.get('placeholder', ''),
                'element_type': 'input'
            }
        
        elif field_type == 'select':
            options = []
            for option in field.find_all('option'):
                options.append({
                    'value': option.get('value', option.get_text().strip()),
                    'text': option.get_text().strip(),
                    'selected': option.has_attr('selected')
                })
            
            return {
                'name': field.get('name'),
                'id': field.get('id'),
                'type': 'select',
                'options': options,
                'required': field.has_attr('required'),
                'element_type': 'select'
            }
        
        elif field_type == 'textarea':
            return {
                'name': field.get('name'),
                'id': field.get('id'),
                'type': 'textarea',
                'value': field.get_text().strip(),
                'required': field.has_attr('required'),
                'placeholder': field.get('placeholder', ''),
                'element_type': 'textarea'
            }
        
        return None
    
    def generate_script(self, forms: List[Dict[str, Any]]) -> str:
        """Generate a Python script that can submit to the extracted forms"""
        
        script_template = '''#!/usr/bin/env python3
"""
Auto-generated form submission script
Generated from: {url}
"""

import requests
from urllib.parse import urljoin

class FormSubmitter:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({{
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }})
    
{form_methods}

if __name__ == "__main__":
    submitter = FormSubmitter()
    
{example_usage}
'''
        
        form_methods = ""
        example_usage = ""
        
        for form in forms:
            method_name = f"submit_form_{form['index']}"
            
            # Generate method for each form
            form_method = f'''    def {method_name}(self{self._generate_parameters(form)}):
        """
        Submit form {form['index']}
        Action: {form['action']}
        Method: {form['method'].upper()}
        """
        
        data = {{
{self._generate_data_dict(form)}        }}
        
        try:
            response = self.session.{form['method']}(
                "{form['action']}", 
                data=data
            )
            response.raise_for_status()
            print(f"Form {form['index']} submitted successfully!")
            print(f"Status: {{response.status_code}}")
            return response
        except requests.RequestException as e:
            print(f"Error submitting form {form['index']}: {{e}}")
            return None
'''
            
            form_methods += form_method + "\n"
            
            # Generate example usage
            example_params = self._generate_example_params(form)
            example_usage += f'    r = submitter.{method_name}({example_params})\n    print(r.text)\n\n'
        
        return script_template.format(
            url=self.url,
            form_methods=form_methods,
            example_usage=example_usage
        )
    
    def _generate_parameters(self, form: Dict[str, Any]) -> str:
        """Generate method parameters for form fields"""
        params = []
        for field in form['fields']:
            if field['name']:
                param_name = field['name'].replace('-', '_').replace('[]', '_list')
                if field['required']:
                    params.append(f", {param_name}")
                else:
                    default_val = f'"{field.get("value", "")}"' if field.get('value') else 'None'
                    params.append(f", {param_name}={default_val}")
        
        return "".join(params)
    
    def _generate_data_dict(self, form: Dict[str, Any]) -> str:
        """Generate the data dictionary for form submission"""
        data_lines = []
        
        for field in form['fields']:
            if field['name']:
                param_name = field['name'].replace('-', '_').replace('[]', '_list')
                
                if field['type'] == 'hidden':
                    # Use the existing value for hidden fields
                    value = f'"{field.get("value", "")}"'
                else:
                    value = param_name
                
                data_lines.append(f'            "{field["name"]}": {value},')
        
        return "\n".join(data_lines)
    
    def _generate_example_params(self, form: Dict[str, Any]) -> str:
        """Generate example parameters for the usage section"""
        params = []
        for field in form['fields']:
            if field['name'] and field['type'] != 'hidden':
                param_name = field['name'].replace('-', '_').replace('[]', '_list')
                
                if field['type'] == 'email':
                    example = '"user@example.com"'
                elif field['type'] == 'password':
                    example = '"your_password"'
                elif field['type'] == 'select' and field.get('options'):
                    example = f'"{field["options"][0]["value"]}"'
                else:
                    example = f'"example_{param_name}"'
                
                params.append(f'{param_name}={example}')
        
        return ", ".join(params)
    
    def print_form_summary(self, forms: List[Dict[str, Any]]):
        """Print a summary of extracted forms"""
        print(f"\n=== EXTRACTED FORMS FROM {self.url} ===\n")
        
        for form in forms:
            print(f"Form {form['index']}:")
            print(f"  Action: {form['action']}")
            print(f"  Method: {form['method'].upper()}")
            print(f"  Fields ({len(form['fields'])}):")
            
            for field in form['fields']:
                required = " (required)" if field.get('required') else ""
                if field['type'] == 'select':
                    options_info = f" - {len(field.get('options', []))} options"
                else:
                    options_info = ""
                
                print(f"    - {field['name']}: {field['type']}{required}{options_info}")
            
            if form['csrf_token']:
                print(f"  CSRF Token: {form['csrf_token']}")
            print()

def main():
    parser = argparse.ArgumentParser(description='Extract form fields and generate submission script')
    parser.add_argument('url', help='URL of the webpage to analyze')
    parser.add_argument('-o', '--output', help='Output file for generated script', default='generated_form_script.py')
    parser.add_argument('-s', '--summary', action='store_true', help='Print form summary only')
    
    args = parser.parse_args()
    
    print(f"Analyzing forms on: {args.url}")
    
    extractor = FormExtractor(args.url)
    soup = extractor.fetch_page()
    forms = extractor.extract_forms(soup)
    
    if not forms:
        print("No forms found on the page.")
        return
    
    extractor.print_form_summary(forms)
    
    if not args.summary:
        script_content = extractor.generate_script(forms)
        
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        print(f"Generated script saved to: {args.output}")
        print("\nTo use the generated script:")
        print(f"python {args.output}")

if __name__ == "__main__":
    main()

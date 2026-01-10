import datetime
import glob
import os
import secrets
import sys
import uuid

try:
    import yaml
except ImportError:
    print("Error: PyYAML is not installed. Please install it using 'pip install pyyaml'.")
    sys.exit(1)

GED_FILE = 'locations.ged'
DATA_DIR = 'data'

def parse_gedcom_lines(lines):
    all_records = []
    id_map = {}
    
    stack = [] # (level, node_ref)
    
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        parts = stripped.split(' ', 2)
        try:
            level = int(parts[0])
        except ValueError:
            continue
            
        # Parse Xref, Tag, Value
        # Standard: Level [Xref] Tag [Value]
        if len(parts) > 1 and parts[1].startswith('@') and parts[1].endswith('@'):
            xref_id = parts[1]
            # If parts has > 3 items, or value contains spaces, simpler parsing needed?
            # stripped.split(' ', 2) already splits into max 3 chunks.
            # 0 @id@ TAG VALUE -> parts[0]=0, parts[1]=@id@, parts[2]=TAG VALUE
            # BUT parts[2] will be "TAG VALUE". We need to split TAG and VALUE.
            
            if len(parts) > 2:
                rest = parts[2]
                rest_parts = rest.split(' ', 1)
                tag = rest_parts[0]
                value = rest_parts[1] if len(rest_parts) > 1 else ""
            else:
                tag = ""
                value = ""
        else:
            xref_id = None
            tag = parts[1]
            value = parts[2] if len(parts) > 2 else ""

        # Special Check: Detect malformed records from previous failed run
        # Malformed: level=0, tag='_LOC', value='@L... @', xref_id=None
        if level == 0 and tag == '_LOC' and value.startswith('@') and value.endswith('@') and not xref_id:
            # Skip this garbage
            continue
            
        node = {'level': level, 'tag': tag, 'value': value, 'xref_id': xref_id, 'children': []}
        
        if level == 0:
            all_records.append(node)
            stack = [(0, node)]
            
            # Map IDs for _LOC records
            if tag == '_LOC' and xref_id:
                rec_id = xref_id.strip('@')
                id_map[rec_id] = node
        else:
            # Find parent - strict hierarchy
            # we need parent level to be level - 1?
            # Or just < level? Standard says level+1, but we should be robust.
            while stack and stack[-1][0] >= level:
                stack.pop()
            
            if stack:
                stack[-1][1]['children'].append(node)
                stack.append((level, node))
            else:
                pass
                
    return all_records, id_map

def parse_gedcom(file_path):
    if not os.path.exists(file_path):
        return [], {}

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    return parse_gedcom_lines(lines)

def load_yaml_data():
    files = glob.glob(os.path.join(DATA_DIR, '**/*.yaml'), recursive=True)
    combined = {}
    for f in files:
        with open(f, 'r', encoding='utf-8') as yf:
            try:
                data = yaml.safe_load(yf)
                if data and isinstance(data, list):
                    for item in data:
                        if 'id' in item:
                            combined[item['id']] = item
            except yaml.YAMLError as exc:
                print(f"Error parsing {f}: {exc}")
    return combined

def generate_uid():
    return uuid.uuid4().hex.upper()

def create_chan_node():
    now = datetime.datetime.now(datetime.timezone.utc)
    date_str = now.strftime("%d %b %Y").upper()
    time_str = now.strftime("%H:%M:%S.%f")[:-5] # 1 decimal place
    
    return {
        'level': 1, 'tag': 'CHAN', 'value': '', 'xref_id': None, 'children': [
            {'level': 2, 'tag': 'DATE', 'value': date_str, 'xref_id': None, 'children': [
                {'level': 3, 'tag': 'TIME', 'value': time_str, 'xref_id': None, 'children': []}
            ]}
        ]
    }

def update_record(record, yaml_item):
    name_abbrs = {}
    
    # We want to preserve specific tags
    preserved_tags = ['_UID', 'MAP', 'NOTE', 'SOUR', 'CHAR', 'LANG', 'GEDC'] 
    
    preserved_children = []
    has_uid = False
    existing_chan = None
    
    for child in record['children']:
        if child['tag'] == 'NAME':
            name_val = child['value']
            for sub in child['children']:
                if sub['tag'] == 'ABBR':
                    name_abbrs[name_val] = sub['value']
        elif child['tag'] == '_UID':
            preserved_children.append(child)
            has_uid = True
        elif child['tag'] == 'CHAN':
            existing_chan = child
        elif child['tag'] not in ['NAME', '_LOC', 'CHAN']:
            preserved_children.append(child)
            
    if not has_uid:
        preserved_children.insert(0, {'level': 1, 'tag': '_UID', 'value': generate_uid(), 'xref_id': None, 'children': []})
        
    new_children = []
    
    # Names
    if 'names' in yaml_item:
        for n in yaml_item['names']:
            name_node = {'level': 1, 'tag': 'NAME', 'value': n['name'], 'xref_id': None, 'children': []}
            
            if n['name'] in name_abbrs:
                name_node['children'].append({'level': 2, 'tag': 'ABBR', 'value': name_abbrs[n['name']], 'xref_id': None, 'children': []})
            
            if 'period' in n:
                name_node['children'].append({'level': 2, 'tag': 'DATE', 'value': n['period'], 'xref_id': None, 'children': []})
            
            new_children.append(name_node)
            
    # Parents (as child _LOC nodes)
    if 'parents' in yaml_item:
        for p in yaml_item['parents']:
             pid = p.get('id')
             if pid:
                 loc_val = f"@{pid}@"
                 loc_node = {'level': 1, 'tag': '_LOC', 'value': loc_val, 'xref_id': None, 'children': []}
                 if 'period' in p:
                     loc_node['children'].append({'level': 2, 'tag': 'DATE', 'value': p['period'], 'xref_id': None, 'children': []})
                 new_children.append(loc_node)
                 
    # Reassemble
    uid_nodes = [c for c in preserved_children if c['tag'] == '_UID']
    other_preserved = [c for c in preserved_children if c['tag'] != '_UID']
    
    final_list = []
    final_list.extend(uid_nodes)
    
    if existing_chan:
        final_list.append(existing_chan)
    else:
        final_list.append(create_chan_node())
        
    final_list.extend(other_preserved)
    final_list.extend(new_children)
    
    record['children'] = final_list

def create_new_record(rec_id, yaml_item):
    # Just delegate to update_record logic by creating a skeleton
    record = {
        'level': 0,
        'tag': '_LOC',
        'value': '',
        'xref_id': f"@{rec_id}@",
        'children': []
    }
    update_record(record, yaml_item)
    return record

def serialize_record(record):
    lines = []
    parts = [str(record['level'])]
    if record['xref_id']:
        parts.append(record['xref_id'])
    parts.append(record['tag'])
    if record['value']:
        parts.append(record['value'])
        
    lines.append(" ".join(parts))
    
    for child in record['children']:
        lines.append(serialize_record(child))
        
    return "\n".join(lines)

def main():
    print("Reading GEDCOM...")
    records, id_map = parse_gedcom(GED_FILE)
    
    print(f"Found {len(records)} records.")
    
    print("Reading YAML...")
    yaml_data = load_yaml_data()
    print(f"Found {len(yaml_data)} YAML items.")
    
    updated_count = 0
    created_count = 0
    
    # Track which IDs have been processed to handle orphans if needed? 
    # For now just update/append.
    
    for y_id, y_item in yaml_data.items():
        if y_id in id_map:
            update_record(id_map[y_id], y_item)
            updated_count += 1
        else:
            new_rec = create_new_record(y_id, y_item)
            records.append(new_rec)
            id_map[y_id] = new_rec
            created_count += 1
            
    # Move TRLR to end
    trlr_index = -1
    for i, r in enumerate(records):
        if r['tag'] == 'TRLR':
            trlr_index = i
            break
            
    if trlr_index != -1:
        trlr = records.pop(trlr_index)
        records.append(trlr)
    else:
        records.append({'level': 0, 'tag': 'TRLR', 'value': '', 'xref_id': None, 'children': []})
        
    print(f"Updated {updated_count} records. Created {created_count} records.")
    
    print("Writing GEDCOM...")
    with open(GED_FILE, 'w', encoding='utf-8') as f:
        for rec in records:
            f.write(serialize_record(rec) + "\n")
            
    print("Done.")

if __name__ == '__main__':
    main()

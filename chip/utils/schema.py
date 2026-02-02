def clean_schema(schema):
    """
    Aggressively simplifies JSON schemas for Google GenAI compatibility.
    Removes 'oneOf', 'anyOf', 'default', and 'const'.
    """
    if not isinstance(schema, dict):
        return schema
    
    s = schema.copy()
    
    for k in ['default', 'title', 'examples', '$schema', 'additionalProperties']:
        s.pop(k, None)
        
    if 'const' in s:
        s['enum'] = [s.pop('const')]
    for key in ['oneOf', 'anyOf']:
        if key in s:
            options = s.pop(key)
            if isinstance(options, list) and len(options) > 0:
                first_opt = clean_schema(options[0])
                # If the first option is just "null", try the second
                if first_opt.get('type') == 'null' and len(options) > 1:
                    first_opt = clean_schema(options[1])
                s.update(first_opt)

    if isinstance(s.get('type'), list):
        valid_types = [t for t in s['type'] if t != 'null']
        s['type'] = valid_types[0] if valid_types else 'string'

    if 'properties' in s:
        for k, v in s['properties'].items():
            s['properties'][k] = clean_schema(v)
            
    if 'items' in s:
        s['items'] = clean_schema(s['items'])
        
    return s
#include "parser.h"
/**
 ** Split a buffer into individual words, at any whitespace or separator
 **/

void
split_string(char *buf, int *argc, char ***argv, char *s)
{
    char sep[256] = " \t\n\r";
    int size = 16;
    int count = 0;
    char *ptr = buf;
    char *p;
 
    if (s) strcat(sep, s);

    *argv = (char **)calloc(size, sizeof(char *));
    while((p = strtok(ptr, sep)) != NULL) {
        (*argv)[count++] = p;
        ptr = NULL;
        if (count == size) {
            size *= 2;
            *argv = (char **)my_realloc(*argv, size*sizeof(char *));
        }
    }
    *argc = count;
}

char *
uppercase(char *s)
{
  char *p;
  for (p = s ; p && *p ; p++) {
    if (islower(*p)) *p = *p - 'a' + 'A';
  }
  return(s);
}

char *
lowercase(char *s)
{
  char *p;
  for (p = s ; p && *p ; p++) {
    if (isupper(*p)) *p = *p - 'A' + 'a';
  }
  return(s);
}

char *
ltrim(char *s, char *trim_chars)
{
	int st = 0;
	while(s[st] && strchr(trim_chars, s[st]))
		st++;
	
	if (st > 0)
		memmove(s, &s[st], strlen(&s[st])+1);

	return s;
}

char *
rtrim(char *s, char *trim_chars)
{
	int len = strlen(s);

	while(len > 0 && strchr(trim_chars, s[len-1]))
		s[--len] = '\0';
	
	return s;
}

/*
 * @param str [in/out] string to be trimmed of characters on both ends
 * @param opt_chars [in] characters to trim, pass as NULL to use isspace()
 * @return str
 */
char *
trim(char *str, const char *opt_chars){
	int n = strlen(str)-1;
	int i;

	// trim white space on the right
	while(n>=0 && (opt_chars == NULL? isspace(str[n]): strchr(opt_chars,str[n]) != NULL)){
		str[n--] = '\0';
	}
	n++;

	// trim white space on the left
	for(i=0; i<n; i++){
		if (!(opt_chars == NULL? isspace(str[i]): strchr(opt_chars, str[i]) != NULL)){
			break;
		}
	}
	memmove(&str[0], &str[i], n-i+1);

	return str;
}


char *
fix_name(const char *input_name, int locase)
{
  const char invalid_pfx[] = "__invalid";
  static int invalid_id = 0;
  char *name;
  int len;
  int i;
  int val;
  const char *trim_chars = "\"\t ";

  name = (char *)calloc(1, strlen(input_name)+strlen(invalid_pfx)+5);
  strcpy(name, input_name);

  ltrim(name, trim_chars);
  rtrim(name, trim_chars);

  len =  strlen(name);
  if (len < 1){
    name = (char *)realloc(name, strlen(invalid_pfx)+12);
    sprintf(name, "%s_%d", invalid_pfx, ++invalid_id);
    return (name);
  }

  for(i=0; i<len; i++){
	name[i] = isalnum(name[i])? (locase?tolower(name[i]):name[i]): '_';
  }

  if (isdigit(name[0])){
	for(i=len; i>=0; i--){
		name[i+1] = name[i];
	}
	name[0] = '_';
  }

  return (name);
}

/**
 * Generates unused key name from specified "keyname" so that
 * it does not clash with a key in structure "s".
 * The returned key has the form keyname_#.
 * If first_instance_special is non-zero, the keyname will be
 * returned as is if it does not exist in "s", otherwise, it
 * 2ill follow the keyname_# structure.
 */
char *
gen_next_unused_name_instance(
    char *keyname,
    Var  *s,
	int first_instance_special
                              )
{
  char *ser_key_name;
  int   i;
  int   max_ser_no = 1000;
  Var  *v;

  /* alloc a ridiculously large key name buffer */
  ser_key_name = (char *)calloc(strlen(keyname)+64, sizeof(char));
  strcpy(ser_key_name, keyname);

  if (first_instance_special){
  	/* if special handling is requested, return the key as is if not found in s */
  	if (find_struct(s, ser_key_name, &v) < 0){
		return ser_key_name;
	}
  }

  for(i = 1; i < max_ser_no; i++){
    /* generate a key with the next free serial number */
    sprintf(ser_key_name, "%s_%d", keyname, i);

    if (find_struct(s, ser_key_name, &v) < 0){
      /* if this serial number is unused, return this key */
      return ser_key_name;
    }
  }

  free(ser_key_name);

  return NULL; /* no such instance found */
}


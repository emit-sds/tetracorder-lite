/*
 * a = load_isis3("/u/ddoerres/work/Project/themis_dbtools/themis_dbtools/trunk/makerdr/I01001001.cub")
 * b = load_isis3("/local/cube/SE_500K_0_0_SIMP.cub")
 * c = load_isis3("/local/cube/ESP_038117_1385_RED.cub")             <-- This is the really big cube
 * d = load_isis3("/u/cedwards/davinci_test/I01001001.lev1.cub")
 * e = load_isis3("/local/cube/32bit_msb_float.cub")
 *
 */

#include "isis3Include.h"

#include "dvio.h"

#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <ctype.h>
#include <libgen.h>
#include <search.h>

#include <sys/stat.h>

#define _FILE_OFFSET_BITS 64

#define MIN(x,y) ((x)<(y)? (x): (y))
#define MAX(x,y) ((x)>(y)? (x): (y))

#define ISIS3_OBJ_TYPE_KEY "__obj_type"
#define ISIS3_STRUCT_TYPE_KEY "isis_struct_type"

#define SFX_UNITS       "_units"
#define PFX_PTR         "ptr_to_"
#define NM_DATA_ELEMENT "data"

#define DEFAULT_TILE_SAMPLES 128
#define DEFAULT_TILE_LINES   128

#define KW_OBJ_ISISCUBE "IsisCube"
#define KW_OBJ_CORE     "Core"
#define KW_OBJ_LABEL    "Label"
#define KW_OBJ_HISTORY  "History"
#define KW_OBJ_TABLE    "Table"
#define KW_OBJ_ORGLBL   "OriginalLabel"
#define KW_OBJ_NAIFKWS  "NaifKeywords"

#define KW_GRP_PIXELS   "Pixels"
#define KW_GRP_DIMS     "Dimensions"
#define KW_GRP_FIELD    "Field"

#define KW_BANDS        "Bands"
#define KW_SAMPLES      "Samples"
#define KW_LINES        "Lines"
#define KW_TSAMPLES     "TileSamples"
#define KW_TLINES       "TileLines"
#define KW_FORMAT       "Format"
#define KW_START_BYTE   "StartByte"
#define KW_SIZE         "Size"
#define KW_TYPE         "Type"
#define KW_BYTE_ORDER   "ByteOrder"
#define KW_BASE         "Base"
#define KW_MULTIPLIER   "Multiplier"
#define KW_COREDATA     "cube"
#define KW_NAME         "Name"
#define KW_BYTES        "Bytes"
#define KW_RECORDS      "Records"

#define KW_OBJ          "Object"
#define KW_GRP          "Group"
#define KW_OBJ_END      "End_Object"
#define KW_GRP_END      "End_Group"
#define KW_END          "End"

#define KW_FMT_BSQ      "BandSequential"
#define KW_FMT_TILE     "Tile"

#define KW_VAL_MSB      "Msb"
#define KW_VAL_LSB      "Lsb"

// core cube data types
#define KW_TYPE_UBYTE   "UnsignedByte"
#define KW_TYPE_SBYTE   "SignedByte"
#define KW_TYPE_UWORD   "UnsignedWord"
#define KW_TYPE_SWORD   "SignedWord"
#define KW_TYPE_UINT    "UnsignedInteger"
#define KW_TYPE_SINT    "SignedInteger"

// table field data types
#define KW_TYPE_INT     "Integer"
#define KW_TYPE_TEXT    "Text"

// common types between core data and table fields
#define KW_TYPE_REAL    "Real"
#define KW_TYPE_DOUBLE  "Double"

// isis_struct_type values
#define IST_VAL_HISTORY "history"

const char *ISIS3_CORE_TYPES[] = {
	KW_TYPE_UBYTE, KW_TYPE_SBYTE, KW_TYPE_UWORD, KW_TYPE_SWORD, KW_TYPE_UINT, KW_TYPE_SINT, KW_TYPE_REAL, KW_TYPE_DOUBLE
};

const char *ISIS3_TBL_FIELD_TYPES[] = {
	KW_TYPE_INT, KW_TYPE_REAL, KW_TYPE_DOUBLE, KW_TYPE_TEXT
};

// number of spaces at each level
#define LVL_SPACES(level) (4*(level))

// duplicate string in an (automatic) stack variable
#define strdupa(s) strcpy((char *)alloca(strlen(s)+1),(s))

static const char *ISIS3_KNOWN_OBJECTS[] = {
	KW_OBJ_ISISCUBE,
	KW_OBJ_CORE,
	KW_OBJ_LABEL,
	KW_OBJ_HISTORY,
	KW_OBJ_TABLE,
	KW_OBJ_ORGLBL,
	KW_OBJ_NAIFKWS
};

struct Isis3Field {
	const char *objName;
	const char *name;
	iom_edf eFmt;
	iom_idf iFmt;
	int isText;
	int byteOffset;
	int itemSize;
	int itemCount;
	int byteSize;
};

static Var *do_loadISIS3(vfuncptr func, char *filename, int read_data, int use_names,
		int use_units, int include_tables, int include_original_label, int mimic_io_module);

static Var *do_writeISIS3(Var *obj, char *ISIS3_filename);
static void findIsis3ObjsByType(Var *objRoot, const char *objType, Var ***found, char ***foundNames, Var ***foundParents, int *nFound);
static int findFirstIsis3ObjByType(Var *objRoot, const char *objType, Var **found, char **foundName, Var **foundParent);

static Var *traverseIsis3Lbl(const char *lbl_file_name, FILE *fp, Var *root, int use_names, int use_units, int read_data, const char *path, int *line_num, long file_limit);
static int updateKwIntValInObj(Var *root, const char *objType, const char *kwName, const int newKwVal);
static int updateKwLongValInObj(Var *root, const char *objType, const char *kwName, const long newKwVal);
static int updateKwDblValInObj(Var *root, const char *objType, const char *kwName, const double newKwVal);
static int undoReorgIsis3HistoryObj(Var *root);
static int writeIsis3Lbl(Var *root, FILE *fp);
iom_edf iomConvertIsis3Type(const char *type, const char *byteOrder, int *isText);
static int readTiledData(FILE *fp, int bytes_per_sample, int samples, int lines, int bands, int tile_width, int tile_height, char **output);
static int writeTiledData(FILE *fp, int bytes_per_sample, int samples, int lines, int bands, int tile_width, int tile_height, const char *data);
static struct Isis3Field *findTblFields(Var *coreObj, int *nFields);

static char *buildUnitKey(const char *name);

static char get_keyword_datatype(char *value, char *name);


/*
 * a = load_isis3("/u/ddoerres/work/Project/themis_dbtools/themis_dbtools/trunk/makerdr/I01001001.cub")
 * write_isis3(a, "Cow", force = 1)
 * b = load_isis3("Cow")
 * write_isis3(b, "Cow", force = 1)
 * b = load_isis3("Cow")
 */

Var *
WriteISIS3(vfuncptr func, Var * arg)
{
	Var *obj = NULL;
	char *filename = NULL;
	int force = 0;

	static char bsqItem[] = KW_FMT_BSQ;
	static char tileItem[] = KW_FMT_TILE;

	if (arg == NULL) {
		parse_error("%s: No parameter list supplied--must supply at least an ISIS3 object and file name.\n", func->name);
		return (NULL);
	}

	Alist alist[4];
	alist[0] = make_alist("obj", ID_UNK, NULL, &obj);
	alist[1] = make_alist("filename", ID_STRING, NULL, &filename);
	alist[2] = make_alist("force", INT, NULL, &force);
	alist[3].name = NULL;

	if (parse_args(func, arg, alist) == 0) {
		parse_error("%s: No useful command line, should have: ISIS3object, \"filename\", [force=0,1]", func->name);
		return NULL;
	}

	if (obj == NULL) {
		parse_error("%s: No ISIS3 object specified.", func->name);
		return NULL;
	}

	if (filename == NULL) {
		parse_error("%s: No filename specified.", func->name);
		return NULL;
	}

	if (!force && access(filename, F_OK) == 0) {
		parse_error("%s: File %s already exists.", func->name, filename);
		return (NULL);
	}

	if ((V_TYPE(obj) == ID_STRUCT)) {
		return (do_writeISIS3(obj, filename));
	} else {
		parse_error("%s: Unhandled object type %d.", func->name, V_TYPE(obj));
		return NULL;
	}
}



// ISIS3 cube keywords to update: "Samples", "Lines", "Bands", "TileSamples", "TileLines", "StartByte", "Bytes", "Records"

static int
moveCoreDataToCube(Var *root){
	const char *coreObjType = KW_OBJ_CORE;
	char *coreObjName = NULL;
	Var *coreObj = NULL, *coreObjParent = NULL;
	Var *coreData = NULL;
	const char *coreDataObjName = KW_COREDATA;
	int rc = 0;

	if (find_struct(root, coreDataObjName, NULL) >= 0){
		coreData = remove_struct_by_key(root, strdup(coreDataObjName));
		if (coreData != NULL){
			mem_claim(coreData);

			if (findFirstIsis3ObjByType(root,coreObjType,&coreObj,&coreObjName,&coreObjParent)){
				add_struct(coreObj, strdup("data"), coreData);
				rc=1;
			}
			else {
				if (VERBOSE > 3)
					fprintf(stderr, "Unable to find \"%s\" obj\n", coreObjType);
			}
		}
		else {
			fprintf(stderr, "Unable to remove \"%s\" from top-level (%p)\n", coreDataObjName, root);
		}
	}
	else {
		if (VERBOSE > 3)
			fprintf(stderr, "Did not find \"%s\" at top level (%p)\n", coreDataObjName, root);
	}

	return rc;
}

// Remove named objects from struct and free their values
static void
removeAndFreeVarsByKeys(Var *structObj, const char **keys, const int nKeys){
	int i;
	char *tmpName = NULL;
	Var *e = NULL;

	for(i=0; i<nKeys; i++){
		e = remove_struct_by_key(structObj, tmpName = strdup(keys[i]));
		if (e != NULL){
			mem_claim(e);
			free_var(e);
		}
		else {
			if (VERBOSE > 3)
				fprintf(stderr, "Unable to find key \"%s\" in struct (%p).\n", keys[i], structObj);
			if (tmpName)
				free(tmpName);
		}
	}
}

// called after moveCoreDataToCube() otherwise "data" will not exist in "Core"
static int
updateDimsFromCoreData(Var *root){
	const char *coreObjType = KW_OBJ_CORE;
	char *coreObjName = NULL;
	Var *coreObj = NULL, *coreObjParent = NULL;
	const char *coreDataObjName = "data", *dimsObjName = KW_GRP_DIMS;
	Var *coreDataObj = NULL;
	Var *dimsObj = NULL;
	const char *dimObjNames[] = { KW_SAMPLES, KW_LINES, KW_BANDS };
	Var *fmtVar = NULL, *tSamplesVar = NULL, *tLinesVar = NULL;
	int samples=0, lines=0, bands=0, tSamples=0, tLines=0;

	if (findFirstIsis3ObjByType(root,coreObjType,&coreObj,&coreObjName,&coreObjParent)){
		if (find_struct(coreObj, coreDataObjName, &coreDataObj) < 0){
			fprintf(stderr, "Unable to find %s. Not updating %s.\n", coreDataObjName, dimsObjName);
			return 0;
		}
		if (find_struct(coreObj, dimsObjName, &dimsObj) < 0){
			add_struct(coreObj, strdup(KW_GRP_DIMS), dimsObj = new_struct(0));
		}
		if (find_struct(coreObj, KW_FORMAT, &fmtVar) < 0){
			add_struct(coreObj, strdup(KW_FORMAT), fmtVar = newString(KW_FMT_BSQ));
		}
		if (find_struct(coreObj, KW_TSAMPLES, &tSamplesVar) < 0){
		}
		if (find_struct(coreObj, KW_TLINES, &tLinesVar) < 0){
		}

		samples = GetX(coreDataObj);
		lines = GetY(coreDataObj);
		bands = GetZ(coreDataObj);

		// remove Samples, Lines and Bands
		//removeAndFreeVars(dimsObj, dimObjNames, sizeof(dimObjNames)/sizeof(char*));

		// add updated Samples, Lines and Bands
		add_struct(dimsObj, strdup(KW_SAMPLES), newInt(samples));
		add_struct(dimsObj, strdup(KW_LINES), newInt(lines));
		add_struct(dimsObj, strdup(KW_BANDS), newInt(bands));

		if (strcmp(V_STRING(fmtVar),KW_FMT_TILE) == 0){
			tSamples = (tSamplesVar == NULL)? DEFAULT_TILE_SAMPLES: V_INT(tSamplesVar);
			tLines = (tLinesVar == NULL)? DEFAULT_TILE_LINES: V_INT(tLinesVar);
			
			tSamples = MIN(samples,tSamples);
			tLines = MIN(lines,tLines);

			add_struct(coreObj, strdup(KW_TSAMPLES), newInt(tSamples));
			add_struct(coreObj, strdup(KW_TLINES), newInt(tLines));
		}
	}
	else {
		if (VERBOSE > 3)
			fprintf(stderr, "Unable to find \"%s\" obj\n", coreObjType);
	}
	
	return 1;
}

static char *
varFmtToIsis3CoreType(Var *var){
	char *coreTypeStr = "Unknown";

	switch(V_TYPE(var)){
	case BYTE: coreTypeStr = KW_TYPE_UBYTE; break;
	case SHORT: coreTypeStr = KW_TYPE_SWORD; break;
	case INT: coreTypeStr = KW_TYPE_INT; break;
	case FLOAT: coreTypeStr = KW_TYPE_REAL; break;
	case DOUBLE: coreTypeStr = KW_TYPE_DOUBLE; break;
	}

	return coreTypeStr;
}

static char *
varFmtToIsis3FieldType(Var *var){
	char *coreTypeStr = "Unknown";

	switch(V_TYPE(var)){
	case ID_VAL:
		switch(V_FORMAT(var)){
		case INT: coreTypeStr = KW_TYPE_INT; break;
		case FLOAT: coreTypeStr = KW_TYPE_REAL; break;
		case DOUBLE: coreTypeStr = KW_TYPE_DOUBLE; break;
		}
		break;
	case ID_TEXT:
		coreTypeStr = KW_TYPE_TEXT;
		break;
	}

	return coreTypeStr;
}

static int
updatePixelsFromCoreData(Var *root){
	const char *coreObjType = KW_OBJ_CORE;
	char *coreObjName = NULL;
	Var *coreObj = NULL, *coreObjParent = NULL;
	const char *coreDataObjName = "data", *pixelsObjName = KW_GRP_PIXELS;
	Var *coreDataObj = NULL;
	Var *pixelsObj = NULL;

	if (findFirstIsis3ObjByType(root,coreObjType,&coreObj,&coreObjName,&coreObjParent)){
		if (find_struct(coreObj, coreDataObjName, &coreDataObj) < 0){
			fprintf(stderr, "Unable to find %s. Not updating %s.\n", coreDataObjName, pixelsObjName);
		}
		if (find_struct(coreObj, pixelsObjName, &pixelsObj) < 0){
			add_struct(coreObj, strdup(pixelsObjName), pixelsObj = new_struct(0));
		}
		if (find_struct(pixelsObj, KW_TYPE, NULL) < 0){
			add_struct(pixelsObj, strdup(KW_TYPE), newString(strdup(varFmtToIsis3CoreType(coreObj))));
		}
		if (find_struct(pixelsObj, KW_BYTE_ORDER, NULL) < 0){
			add_struct(pixelsObj, strdup(KW_BYTE_ORDER), newString(KW_VAL_LSB));
		}
		if (find_struct(pixelsObj, KW_BASE, NULL) < 0){
			add_struct(pixelsObj, strdup(KW_BASE), newFloat(0.0));
		}
		if (find_struct(pixelsObj, KW_MULTIPLIER, NULL) < 0){
			add_struct(pixelsObj, strdup(KW_MULTIPLIER), newFloat(1.0));
		}
	}

	return 1;
}

static int
moveHistoryFromCubeToTopLevel(Var *root){
	const char *isisCubeObjType = KW_OBJ_ISISCUBE;
	char *isisCubeObjName = NULL;
	Var *isisCubeObj = NULL, *isisCubeObjParent = NULL;
	const char *histObjName = KW_OBJ_HISTORY;
	Var *histObj = NULL;

	if (findFirstIsis3ObjByType(root,isisCubeObjType,&isisCubeObj,&isisCubeObjName,&isisCubeObjParent)){
		if (find_struct(isisCubeObj, histObjName, NULL) < 0){
			if (VERBOSE > 3)
				fprintf(stderr, "Did not find %s object in %s object (%p)\n", histObjName, isisCubeObjType, isisCubeObj);
		}
		else {
			histObj = remove_struct_by_key(isisCubeObj, histObjName);
			if (histObj == NULL){
				fprintf(stderr, "Unable to remove %s object from %s object (%p)\n", histObjName, isisCubeObjType, isisCubeObj);
			}
			else {
				mem_claim(histObj);
				add_struct(root, strdup(histObjName), histObj);
				return 1;
			}
		}
	}

	return 0;
}

// TODO START HERE
static int
updateIsis3TableFieldStruct(Var *fieldObj, const char *fieldName, Var *tableObj, Var *fieldDataObj){
	char *str = NULL;

	if (find_struct(fieldObj, KW_NAME, NULL) < 0){
		add_struct(fieldObj, strdup(KW_NAME), newString(strdup(fieldName)));
	}

	if (fieldDataObj != NULL){
		if (find_struct(fieldObj, KW_TYPE, NULL) < 0){
			add_struct(fieldObj, strdup(KW_TYPE), newString(strdup(varFmtToIsis3FieldType(fieldDataObj))));
		}
		add_struct(fieldObj, str=strdup(KW_SIZE), newInt(GetX(fieldDataObj)));
	}

	if (find_struct(fieldObj, ISIS3_OBJ_TYPE_KEY, NULL) < 0){
		add_struct(fieldObj, strdup(ISIS3_OBJ_TYPE_KEY), newString(strdup(KW_GRP_FIELD)));
	}
}

static int
updateIsis3TableStruct(Var *tableObj, const char *tblName, Var *root){
	const char *funcName = "updateIsis3TableStruct()";
	Var **fieldObjs = NULL;
	char **fieldObjNames = NULL;
	Var **fieldObjParents = NULL;
	int i, nFields = 0;
	int  n;
	int rc = 1;
	Var *eData = NULL, *eFieldData = NULL;
	char *eFieldName = NULL;
	int nTableRows = 0;
	int nColsWithData = 0;
	Var *fieldObj = NULL;
	Var *byteOrderVar = NULL;
	Var *fieldType = NULL, *fieldSize = NULL;
	char *typeStr = NULL;
	int itemCount = 0, rowBytes = 0;
	iom_edf eFmt;
	int isText = 0;
	char *foo = strdup("blah blah");


	find_struct(tableObj, "data", &eData);
	if (find_struct(tableObj, KW_BYTE_ORDER, &byteOrderVar) < 0){
		if (VERBOSE > 3)
			fprintf(stderr, "%s: keyword %s not found in table %s, adding default %s\n",
				funcName, KW_BYTE_ORDER, tblName, KW_VAL_LSB);
		add_struct(tableObj, strdup(KW_BYTE_ORDER), byteOrderVar = newString(strdup(KW_VAL_LSB)));
	}
	
	findIsis3ObjsByType(tableObj, KW_GRP_FIELD, &fieldObjs, &fieldObjNames, &fieldObjParents, &nFields);

	for(i=0; i<nFields; i++){

		eFieldData = NULL;
		if (eData != NULL){
			find_struct(eData, fieldObjNames[i], &eFieldData);

			if (eFieldData != NULL)
				nColsWithData ++;

			if (eFieldData != NULL && GetY(eFieldData) > nTableRows){
				if (nTableRows > 0){
					fprintf(stderr, "%s: table %s incosistent row count %d (vs %d) in column %s\n",
						funcName, tblName, GetY(eFieldData), nTableRows, fieldObjNames[i]);
				}
				nTableRows = GetY(eFieldData);
			}
		}
		updateIsis3TableFieldStruct(fieldObjs[i], fieldObjNames[i], tableObj, eFieldData);
	}

	// add any fields within data sub-struct
	if (eData != NULL){
		n = get_struct_count(eData);

		for(i=0; i<n; i++){
			get_struct_element(eData, i, &eFieldName, &eFieldData);
			if (V_TYPE(eFieldData) == ID_VAL){
				if (find_struct(tableObj, eFieldName, NULL) < 0){
					if (VERBOSE > 3)
						fprintf(stderr, "%s: Did not find field descriptor for %s in table %s. Adding.\n",
							funcName, eFieldName, tblName);

					add_struct(tableObj, strdup(eFieldName), fieldObj = new_struct(0));
					updateIsis3TableFieldStruct(fieldObj, eFieldName, tableObj, eFieldData);

					nColsWithData ++;
					if (nTableRows > 0 && GetY(eFieldData) > nTableRows){
						fprintf(stderr, "%s: table %s incosistent row count %d (vs %d) in column %s\n",
							funcName, tblName, GetY(eFieldData), nTableRows, eFieldName);
						nTableRows = GetY(eFieldData);
					}
				}
			}
		}
	}

	// update row width
	if (fieldObjs != NULL){
		free(fieldObjs);
		free(fieldObjNames);
		free(fieldObjParents);
	}

	fieldObjs = NULL;
	fieldObjNames = NULL;
	fieldObjParents = NULL;
	nFields = 0;
	findIsis3ObjsByType(tableObj, KW_GRP_FIELD, &fieldObjs, &fieldObjNames, &fieldObjParents, &nFields);
	rowBytes = 0;
	for(i=0; i<nFields; i++){
		find_struct(fieldObjs[i], KW_TYPE, &fieldType);
		find_struct(fieldObjs[i], KW_SIZE, &fieldSize);

		// both should exist at this point
		typeStr = V_STRING(fieldType);
		itemCount = V_INT(fieldSize);

		// TODO handle unknown typeStr values
		eFmt = iomConvertIsis3Type(typeStr, V_STRING(byteOrderVar), &isText);
		rowBytes += iom_NBYTES(eFmt) * itemCount;
	}

	add_struct(tableObj, strdup(KW_BYTES), newInt(rowBytes*nTableRows));
	add_struct(tableObj, strdup(KW_RECORDS), newInt(nTableRows));

	if (fieldObjs != NULL){
		free(fieldObjs);
		free(fieldObjNames);
		free(fieldObjParents);
	}

	return 1;
}

static int
updateIsis3TableStructs(Var *root){
	Var **tableObjs = NULL;
	char **tableObjNames = NULL;
	Var **tableObjParents = NULL;
	int i, n = 0;
	int rc = 1;

	findIsis3ObjsByType(root, KW_OBJ_TABLE, &tableObjs, &tableObjNames, &tableObjParents, &n);
	for(i=0; i<n; i++){
		rc = rc && updateIsis3TableStruct(tableObjs[i], tableObjNames[i], root);
	}

	return rc;
}

//

static Var *
updateIsis3Struct(Var *root){
	const char *coreObjType = KW_OBJ_CORE;
	char *coreObjName = NULL;
	Var *coreObj = NULL, *coreObjParent = NULL;

	// TODO check to see if core is at the top-level
	// move core into IsisCube.Cube.data
	moveCoreDataToCube(root);

	// update dimensions and tile dimensions
	updateDimsFromCoreData(root);

	// update pixels group from core data
	updatePixelsFromCoreData(root);

	// reorg History by pushing history structs (either history or with >2 elements)  down into data sub-element
	undoReorgIsis3HistoryObj(root);

	// move IsisCube.Cube.History to top-level
	moveHistoryFromCubeToTopLevel(root);
	
	// handle tables
	updateIsis3TableStructs(root);
}

// returns > 0 for reserved keywords that were added by the ISIS3 reader
static int
isReserved(const char *name){
	if (strcmp(name, ISIS3_OBJ_TYPE_KEY) == 0){
		return 1;
	}
	if (strcmp(name, ISIS3_STRUCT_TYPE_KEY) == 0){
		return 1;
	}
	if (strstr(name,SFX_UNITS) != NULL && 
		strstr(name,SFX_UNITS) == (name+strlen(name)-strlen(SFX_UNITS))){
		return 1;
	}
	if (strncmp(name,PFX_PTR,strlen(PFX_PTR)) == 0){
		return 1;
	}
	return 0;
}

static int
nDigitsAfterDecimal(double d){
	int max_digits = 3 + DBL_MANT_DIG - DBL_MIN_EXP;
	int i;
	
	for(i=0; i<max_digits; i++){
		if (fpclassify(d-rint(d)) == FP_ZERO){
			break;
		}

		d *= 10.0;
	}

	return i;
}

static int
nDigitsAfterDecimal2(double d){
	int max_digits = 3 + DBL_MANT_DIG - DBL_MIN_EXP;
	int i;
	double ipart;
	
	for(i=0; i<max_digits; i++){
		d = modf(d, &ipart);
		if (fpclassify(d) == FP_ZERO){
			break;
		}

		d *= 10.0;
	}

	return i;
}

static int
strHasSpaces(const char *str){
	int i, n = strlen(str);

	for(i=0; i<n; i++){
		if (isspace(str[i])){
			return 1;
		}
	}

	return 0;
}

static int
writeIsis3LblArray(FILE *fp, const char *name, Var *e, Var *eUnit, int level){
	int nItems = 0, nLines = 0;
	int i;
	char **text = NULL;
	int rc = 0;
	char *units = NULL, *unitsTxt = NULL;
	int hasSpaces;
	int nDecimalDigits;
	double d;

	if (eUnit == NULL){
		unitsTxt = "";
	}
	else {
		units = strdupa(V_STRING(eUnit));
		trim(units,NULL);
		unitsTxt = (char *)alloca(strlen(units)+5);
		sprintf(unitsTxt, " <%s>", units);
	}

	switch(V_TYPE(e)){
	case ID_VAL:
		switch(V_FORMAT(e)){
		case BYTE:
		case SHORT:
		case INT:
		case LONG:
			nItems = V_DSIZE(e);
			fprintf(fp, "%*s%s = (", LVL_SPACES(level), "", name);
			for(i=0; i<nItems; i++){
				if (i>0)
					fprintf(fp, ", ");

				fprintf(fp, "%ld", extract_long(e, i));
			}
			fprintf(fp, ")%s\n", unitsTxt);
			break;

		case FLOAT:
		case DOUBLE:
			nItems = V_DSIZE(e);
			fprintf(fp, "%*s%s = (", LVL_SPACES(level), "", name);
			for(i=0; i<nItems; i++){
				if (i>0)
					fprintf(fp, ", ");

				d = extract_double(e,i);
				nDecimalDigits = max(1,nDigitsAfterDecimal(d));
				fprintf(fp, "%.*f", nDecimalDigits, d);
			}
			fprintf(fp, ")%s\n", unitsTxt);
			break;
		}
		break;

	case ID_TEXT:
		nLines = V_TEXT(e).Row;
		text = V_TEXT(e).text;

		fprintf(fp, "%*s%s = (", LVL_SPACES(level), "", name);
		for(i=0; i<nLines; i++){
			if (i>0)
				fprintf(fp, ", ");

			hasSpaces = strHasSpaces(text[i]);
			fprintf(fp, "%s%s%s", (hasSpaces? "\"": ""), text[i], (hasSpaces? "\"": ""));
		}
		fprintf(fp, ")\n");
		break;
	}

	return 1;
}

static int
writeIsis3LblVal(FILE *fp, const char *name, Var *e, Var *eUnit, int level){
	int nItems = 0, nLines = 0;
	int i;
	char **text = NULL;
	int rc = 0;
	char *units = NULL, *unitsTxt = NULL;
	int hasSpaces = 1;
	int nDecimalDigits;
	double d;

	if (eUnit == NULL){
		unitsTxt = "";
	}
	else {
		units = strdupa(V_STRING(eUnit));
		trim(units,NULL);
		unitsTxt = (char *)alloca(strlen(units)+5);
		sprintf(unitsTxt, " <%s>", units);
	}

	switch(V_TYPE(e)){
	case ID_VAL:
		switch(V_FORMAT(e)){
		case BYTE:
		case SHORT:
		case INT:
		case LONG:
			fprintf(fp, "%*s%s = %ld%s\n", LVL_SPACES(level), "", name, extract_long(e,0), unitsTxt);
			break;
		case FLOAT:
		case DOUBLE:
			//fprintf(fp, "%*s%s = %.3f%s\n", LVL_SPACES(level), "", name, extract_double(e,0), unitsTxt);
			d = extract_double(e,0);
			nDecimalDigits = max(1,nDigitsAfterDecimal(d));
			fprintf(fp, "%*s%s = %.*f%s\n", LVL_SPACES(level), "", name, nDecimalDigits, d, unitsTxt);
			break;
		}
		break;
	// TODO only enclose in double quotes if the word has spaces in it
	case ID_STRING:
		hasSpaces = strHasSpaces(V_STRING(e));;
		fprintf(fp, "%*s%s = %s%s%s\n", LVL_SPACES(level), "", name,
			(hasSpaces?"\"":""), V_STRING(e), (hasSpaces?"\"":""));
		break;
	}

	return 1;
}

static char *
buildUnitKey(const char *name){
	static char unitKey[1024];

	sprintf(unitKey,"%s%s", name, SFX_UNITS);

	return unitKey;
}

static int
structIsForObject(Var *s){
	Var *objTypeVar = NULL, *structTypeVar = NULL;
	int i, n = sizeof(ISIS3_KNOWN_OBJECTS)/sizeof(char *);
	char *obj_isis_struct_type = NULL;
	int found;

	if (V_TYPE(s) == ID_STRUCT){
		find_struct(s, ISIS3_OBJ_TYPE_KEY, &objTypeVar);
		find_struct(s, ISIS3_STRUCT_TYPE_KEY, &structTypeVar);
		found = 0;

		if (objTypeVar != NULL){
			for(i=0; i<n; i++){
				if (strcmp(ISIS3_KNOWN_OBJECTS[i], V_STRING(objTypeVar)) == 0){
					found = 1;
					break;
				}
			}
		}
		if (!found && structTypeVar != NULL){
			strcpy(obj_isis_struct_type=(char *)alloca(strlen(KW_OBJ)+1), KW_OBJ);
		    lowercase(obj_isis_struct_type);

			if (strcmp(V_STRING(structTypeVar), obj_isis_struct_type) == 0){
				found = 1;
			}
		}
		if (!found && find_struct(s, "data", NULL) >= 0){
			found = 1;
		}
		if (found){
			return 1;
		}
	}

	return 0;
}

static int
writeIsis3Lbl0(Var *root, const char *rootName, FILE *fp, int level){
	int i=0, j=0, n=0;
	int nLines=0;
	char **text = NULL;
	char *name = NULL;
	Var *e = NULL, *eUnit = NULL;
	char *structType = NULL;
	Var *objType = NULL;

	if (V_TYPE(root) != ID_STRUCT){
		return 0;
	}

	n = get_struct_count(root);
	for(i=0; i<n; i++){

		get_struct_element(root, i, &name, &e);
		if (isReserved(name)){
			continue;
		}
		// (strcmp(rootName,"Core") == 0 && strcmp(name,"data") == 0)
		if (strcmp(name,"data") == 0){
			continue;
		}

		if (V_TYPE(e) == ID_STRUCT){
			if (level > 0 || (level == 0 && i>0)){
				fprintf(fp, "%*s\n", LVL_SPACES(level), "");
			}
			structType = (structIsForObject(e))? KW_OBJ: KW_GRP;
			find_struct(e, ISIS3_OBJ_TYPE_KEY, &objType);
			fprintf(fp, "%*s%s = %s\n", LVL_SPACES(level), "", structType, objType? V_STRING(objType): name); // TODO camelcase name
			writeIsis3Lbl0(e, name, fp, level+1);
			fprintf(fp, "%*s%s_%s\n", LVL_SPACES(level), "", KW_END, structType);
		}
		else {
			// find units
			eUnit = NULL;
			find_struct(root, buildUnitKey(name), &eUnit);

			switch(V_TYPE(e)){
			case ID_VAL:
				if (V_DSIZE(e) > 1){
					writeIsis3LblArray(fp, name, e, eUnit, level);
				}
				else {
					writeIsis3LblVal(fp, name, e, eUnit, level);
				}
				break;

			case ID_STRING:
				writeIsis3LblVal(fp, name, e, eUnit, level);
				break;

			case ID_TEXT:
				writeIsis3LblArray(fp, name, e, eUnit, level);
				break;
			}

			// TODO keep track of StartByte and ByteSize
		}
	}

	if (level == 0){
		fprintf(fp, "%*s%s\n", LVL_SPACES(level), "", KW_END);
	}

	return 1;
}

static int
writeIsis3Lbl(Var *root, FILE *fp){
	return writeIsis3Lbl0(root, "root", fp, 0);
}

static void
swapBytes(char *bytes, int n){
	int i;
	char tmp;

	for(i=0; i<n/2; i++){
		tmp = bytes[i];
		bytes[i] = bytes[n-1-i];
		bytes[n-1-i] = tmp;
	}
}

static char *
convertDoubleToExtFmt(double v, iom_edf edf){
	static char out[8];

	switch(edf){
	case iom_LSB_INT_1:
	case iom_MSB_INT_1: *((unsigned char *)out) = (unsigned char)v; break;

	case iom_LSB_INT_2:
	case iom_MSB_INT_2: *((short *)out) = (short)v; break;

	case iom_LSB_INT_4:
	case iom_MSB_INT_4: *((int *)out) = (int)v; break;

	case iom_LSB_IEEE_REAL_4:
	case iom_MSB_IEEE_REAL_4: *((float *)out) = (float)v; break;

	case iom_LSB_IEEE_REAL_8:
	case iom_MSB_IEEE_REAL_8: *((double *)out) = v; break;
	}

	switch(edf){
	#if WORDS_BIGENDIAN
	case iom_LSB_INT_2:
	case iom_LSB_IEEE_REAL_4:
	case iom_LSB_IEEE_REAL_8:
		swapBytes(out,iom_NBYTES(edf));
		break;
	#else
	case iom_MSB_INT_2:
	case iom_MSB_INT_4:
	case iom_MSB_IEEE_REAL_4:
	case iom_MSB_IEEE_REAL_8:
		swapBytes(out,iom_NBYTES(edf));
		break;
	#endif
	}

	return out;
}

static char *
convertDataToExtFmt(Var *dataObj, double base, double multiplier, iom_edf edf){
	long dataSize = V_DSIZE(dataObj);
	char *obuff = NULL;
	double d;
	int itemBytes = iom_NBYTES(edf);
	const int  *dims = V_SIZE(dataObj);
	int  org = V_ORG(dataObj);
	int x, y, z;
	size_t idx;
	int  oOrg = BSQ;
	int  oDims[3] = { GetX(dataObj), GetY(dataObj), GetX(dataObj) };
	int i;

	obuff = (char *)calloc(dataSize, itemBytes);

	if (obuff != NULL){
		for(i=0; i<dataSize; i++){
			d = extract_double(dataObj, i);
			d = (d - base)/multiplier; // reverse of d = dn * multiplier + base

			// save unscaled value in the output buffer in BSQ org
			iom_Xpos(i, org, dims, &x, &y, &z);
			idx = iom_Cpos(x, y, z, oOrg, oDims);
			memcpy(obuff + idx*itemBytes, convertDoubleToExtFmt(d,edf), itemBytes);
		}
	}

	return obuff;
}

static int
writeIsis3CoreData(Var *root, FILE *fp, const char *fileName){
	const char *coreObjType = KW_OBJ_CORE;
	char *coreObjName = NULL;
	Var *coreObj = NULL, *coreObjParent = NULL;
	const char *coreDataObjName = "data", *dimsObjName = KW_GRP_DIMS, *pixelsObjName = KW_GRP_PIXELS;
	Var *coreDataObj = NULL, *pixelsObj = NULL, *typeVar = NULL, *byteOrderVar = NULL;
	Var *dimsObj = NULL;
	const char *dimObjNames[] = { KW_SAMPLES, KW_LINES, KW_BANDS };
	Var *fmtVar = NULL, *tSamplesVar = NULL, *tLinesVar = NULL;
	Var *multiplierVar = NULL, *baseVar = NULL;
	int samples=0, lines=0, bands=0, tSamples=0, tLines=0;
	double base = 0.0, multiplier = 1.0;
	char *oData = NULL;
	int oItemBytes = 0;
	ssize_t nItems = 0, nWritten = 0;

	if (findFirstIsis3ObjByType(root,coreObjType,&coreObj,&coreObjName,&coreObjParent)){
		if (find_struct(coreObj, coreDataObjName, &coreDataObj) < 0){
			fprintf(stderr, "ERROR! Unable to find %s in %s.\n", coreDataObjName, coreObjType);
			return 0;
		}

		find_struct(coreObj, pixelsObjName, &pixelsObj);
		find_struct(pixelsObj, KW_TYPE, &typeVar);
		find_struct(pixelsObj, KW_BYTE_ORDER, &byteOrderVar);
		find_struct(pixelsObj, KW_BASE, &baseVar);
		find_struct(pixelsObj, KW_MULTIPLIER, &multiplierVar);

		find_struct(coreObj, dimsObjName, &dimsObj);
		find_struct(coreObj, KW_FORMAT, &fmtVar);
		find_struct(coreObj, KW_TSAMPLES, &tSamplesVar);
		find_struct(coreObj, KW_TLINES, &tLinesVar);

		samples = GetX(coreDataObj);
		lines = GetY(coreDataObj);
		bands = GetZ(coreDataObj);
		nItems = (ssize_t)samples * (ssize_t)lines * (ssize_t)bands;

		if (strcmp(V_STRING(fmtVar), KW_FMT_TILE) == 0){
			tSamples = extract_int(tSamplesVar,0);
			tLines = extract_int(tLinesVar,0);
		}

		// reverse the application of scale and offset
		// convert to external format in BSQ org
		iom_edf eFmt = iomConvertIsis3Type(V_STRING(typeVar), V_STRING(byteOrderVar), NULL);
		oItemBytes = iom_NBYTES(eFmt);

		base = extract_double(baseVar, 0);
		multiplier = extract_double(multiplierVar, 0);

		oData = convertDataToExtFmt(coreDataObj, base, multiplier, eFmt);
		if (oData != NULL){
			if (strcmp(V_STRING(fmtVar), KW_FMT_TILE) == 0){
				writeTiledData(fp, oItemBytes, samples, lines, bands, tSamples, tLines, oData);
			}
			else {
				if ((nWritten = fwrite(oData, oItemBytes, nItems, fp)) != nItems){
					fprintf(stderr, "writeIsis3CoreData(): Failed to write %ld items to file \"%s\", actual written %ld. Cause: %s\n",
						nItems, fileName, nWritten, strerror(errno));
				}
			}
			
			free(oData);
		}
	}

	return 1;
}

static int
updateKwValInObj(Var *root, const char *objType, const char *kwName, Var *newKwVal)
{
	char *objName = NULL;
	Var *obj = NULL, *objParent = NULL;
	Var *kwVal = NULL;

	if (findFirstIsis3ObjByType(root,objType,&obj,&objName,&objParent)){
		if (find_struct(obj, kwName, &kwVal) < 0){
			fprintf(stderr, "ERROR! Unable to find %s in %s object.\n", kwName, objType);
			return 0;
		}
		add_struct(obj, strdup(kwName), newKwVal);
	}
	return 1;
}

static int
updateKwIntValInObj(Var *root, const char *objType, const char *kwName, const int newKwVal)
{
	int rc = 0;
	Var *newKwValVar = NULL;

	rc = updateKwValInObj(root, objType, kwName, newKwValVar = newInt(newKwVal));
	if (!rc){
		mem_claim(newKwValVar);
		free_var(newKwValVar);
	}

	return rc;
}

static int
updateKwLongValInObj(Var *root, const char *objType, const char *kwName, const long newKwVal)
{
	int rc = 0;
	Var *newKwValVar = NULL;

	rc = updateKwValInObj(root, objType, kwName, newKwValVar = newLong(newKwVal));
	if (!rc){
		mem_claim(newKwValVar);
		free_var(newKwValVar);
	}

	return rc;
}

static int
updateKwDblValInObj(Var *root, const char *objType, const char *kwName, const double newKwVal)
{
	int rc = 0;
	Var *newKwValVar = NULL;

	rc = updateKwValInObj(root, objType, kwName, newKwValVar = newDouble(newKwVal));
	if (!rc){
		mem_claim(newKwValVar);
		free_var(newKwValVar);
	}

	return rc;
}


static int
updateLabelSize(Var *root, ssize_t labelSize){
	return updateKwIntValInObj(root, KW_OBJ_LABEL, KW_BYTES, labelSize);
}

static int
updateIsis3CoreStartAndSize(Var *root, ssize_t coreStart, ssize_t coreSize){
	return updateKwLongValInObj(root, KW_OBJ_CORE, KW_START_BYTE, coreStart);
}

static int
updateIsis3TableStart(Var *tableObj, ssize_t tableStart){
	add_struct(tableObj, strdup(KW_START_BYTE), newLong(tableStart));
	return 1;
}

static int
updateIsis3OriginalLblStartAndSize(Var *root, ssize_t startByte, ssize_t nBytes){
	int rc = 1;

	rc = rc && updateKwLongValInObj(root, KW_OBJ_ORGLBL, KW_START_BYTE, startByte);
	rc = rc && updateKwIntValInObj(root, KW_OBJ_ORGLBL, KW_BYTES, nBytes);

	return rc;
}

// assumes updateIsis3TableStructs() has been called
static int
writeIsis3Tbl(Var *tableObj, const char * tableName, Var *tableParentObj, FILE *fp, const char *fname){
	const char *funcName = "writeisis3Tbl()";
	struct Isis3Field *fields = NULL;
	int nFields = 0;
	int nRows = 0;
	int tblSize = 0, rowBytes = 0;
	char *buff = NULL;
	Var *bytesVar = NULL, *recordsVar = NULL, *byteOrderVar = NULL;
	Var *dataStruct = NULL;
	Var **fieldDataVars = NULL;
	double d;
	int rc = 0;
	int i, j, k;

	find_struct(tableObj, KW_BYTES, &bytesVar);
	find_struct(tableObj, KW_RECORDS, &recordsVar);
	find_struct(tableObj, KW_BYTE_ORDER, &byteOrderVar);
	find_struct(tableObj, "data", &dataStruct);

	nRows = V_INT(recordsVar);
	tblSize = V_INT(bytesVar);
	rowBytes = nRows > 0? tblSize / nRows: 0;

	buff = (char *)calloc(rowBytes, sizeof(char));
	if (buff == NULL){
		fprintf(stderr, "%s: Unable to alloc %ld bytes for table %s\n", funcName, rowBytes, tableName);
		rc = 0;
	}
	else {
		fields = findTblFields(tableObj, &nFields);

		fieldDataVars = (Var **)calloc(nFields, sizeof(Var *));
		if (fieldDataVars == NULL){
			fprintf(stderr, "%s: Unable to calloc(%ld,%d).\n", funcName, nFields, sizeof(Var *));
			rc = 0;
		}
		else {
			for(i=0; i<nFields; i++){
				// TODO this is a chance for confusion if field name matches object name of another field
				// try looking for data by field name first
				find_struct(dataStruct, fields[i].name, &fieldDataVars[i]);
				if (fieldDataVars[i] == NULL){
					// if that fails, try looking for data by object name
					find_struct(dataStruct, fields[i].objName, &fieldDataVars[i]);
				}
				if (fieldDataVars[i] == NULL){
					fprintf(stderr, "%s: Unable to find data for field %d (with name:%s objName:%s) in table %s.\n", funcName, i, fields[i].name, fields[i].objName, tableName);
				}
			}

			rc = 1;
			for(j=0; j<nRows && rc; j++){
				for(i=0; i<nFields && rc; i++){
					for(k=0; k<fields[i].itemCount; k++){
						d = (fieldDataVars[i] == NULL)? 0.0: 
							extract_double(fieldDataVars[i], cpos(k,j,0,fieldDataVars[i]));
						memcpy(buff + fields[i].byteOffset + k*fields[i].itemSize,
							convertDoubleToExtFmt(d, fields[i].eFmt), fields[i].itemSize);
					}
				}
				if (fwrite(buff, rowBytes, 1, fp) != 1){
					fprintf(stderr, "writeIsis3Tbl(): Unable to write %ld bytes to \"%s\". Cause: %s\n", rowBytes, fname, strerror(errno));
					rc = 0;
				}
			}
		}
	}

	if (buff != NULL)
		free(buff);

	if (fields != NULL)
		free(fields);

	if (fieldDataVars != NULL)
		free(fieldDataVars);

	return rc;
}

static int
writeIsis3Tbls(Var *root, FILE *fp, const char *fname){
	const char *funcName = "writeIsis3Tbls()";
	Var **tableObjs = NULL;
	char **tableNames = NULL;
	Var **tableParentObjs = NULL;
	int nTables = 0;
	ssize_t objStart = 0, objSize = 0;
	int rc = 1;
	int i;

	findIsis3ObjsByType(root, KW_OBJ_TABLE, &tableObjs, &tableNames, &tableParentObjs, &nTables);

	for(i=0; i<nTables && rc; i++){
		objStart = ftell(fp);
		rc = rc && writeIsis3Tbl(tableObjs[i], tableNames[i], tableParentObjs[i], fp, fname);
		objSize = ftell(fp) - objStart;

		if (VERBOSE > 3)
			fprintf(stderr, "%s: Updating Table %s.StartByte to %ld\n", funcName, tableNames[i], objStart+1);
		if (!updateIsis3TableStart(tableObjs[i], objStart+1)){
			fprintf(stderr, "%s: Failed updating Table %s.StartByte to %ld\n", funcName, tableNames[i], objStart+1);
		}
	}

	return rc;
}

static int
writeIsis3OrgLbl(Var *root, FILE *fp, const char *fname){
	const char *funcName = "writeIsis3OrgLbl()";
	Var **orgLblObjs = NULL;
	char **orgLblNames = NULL;
	Var **orgLblParentObjs = NULL;
	int nOrgLbls = 0;
	ssize_t objStart = 0, objSize = 0;
	Var *dataStruct = NULL;
	int rc = 1;
	int i, j;
	int nLines = 0;
	char **lines = NULL;

	findIsis3ObjsByType(root, KW_OBJ_ORGLBL, &orgLblObjs, &orgLblNames, &orgLblParentObjs, &nOrgLbls);
	if (nOrgLbls > 1){
		fprintf(stderr, "%s: More than one (%d) %s objects is unexpected.\n",
			funcName, nOrgLbls, KW_OBJ_ORGLBL);
		rc = 0;
	}
	else {
		rc = 1;

		for(i=0; i<nOrgLbls; i++){
			objStart = ftell(fp);

			find_struct(orgLblObjs[i], "data", &dataStruct);
			if (dataStruct != NULL){
				nLines = V_TEXT(dataStruct).Row;
				lines = V_TEXT(dataStruct).text;
				for(j=0; j<nLines; j++){
					fprintf(fp, "%s\n", lines[j]);
				}
			}

			objSize = ftell(fp) - objStart;

			if (VERBOSE > 3)
				fprintf(stderr, "%s: Updating %s.%s to %d and %s.%s to %d\n", 
					funcName, orgLblNames[i], KW_START_BYTE, objStart+1, orgLblNames[i], KW_BYTES, objSize);
			if (!updateIsis3OriginalLblStartAndSize(root, objStart+1, objSize)){
				fprintf(stderr, "%s: Failed updating %s.%s to %d and %s.%s to %d\n",
					funcName, orgLblNames[i], KW_START_BYTE, objStart+1, orgLblNames[i], KW_BYTES, objSize);
			}
		}
	}

	return rc;
}

static int
updateIsis3HistoryStartAndSize(Var *root, ssize_t startByte, ssize_t nBytes){
	int rc = 1;

	rc = rc && updateKwLongValInObj(root, KW_OBJ_HISTORY, KW_START_BYTE, startByte);
	rc = rc && updateKwIntValInObj(root, KW_OBJ_HISTORY, KW_BYTES, nBytes);

	return rc;
}


static int
writeIsis3History(Var *root, FILE *fp, const char *fname){
	const char *funcName = "writeIsis3History()";
	Var **histObjs = NULL;
	char **histNames = NULL;
	Var **histParentObjs = NULL;
	int nHists = 0;
	ssize_t objStart = 0, objSize = 0;
	Var *dataStruct = NULL;
	int rc = 1;
	int i, j;
	int nLines = 0;
	char **lines = NULL;

	findIsis3ObjsByType(root, KW_OBJ_HISTORY, &histObjs, &histNames, &histParentObjs, &nHists);
	if (nHists > 1){
		fprintf(stderr, "%s: More than one (%d) %s objects is unexpected.\n",
			funcName, nHists, KW_OBJ_HISTORY);
		rc = 0;
	}
	else {
		rc = 1;

		for(i=0; i<nHists; i++){
			objStart = ftell(fp);

			find_struct(histObjs[i], "data", &dataStruct);
			if (dataStruct != NULL){
				writeIsis3Lbl0(dataStruct, "root", fp, 0);
			}

			objSize = ftell(fp) - objStart;

			if (VERBOSE > 3)
				fprintf(stderr, "%s: Updating %s.%s to %d and %s.%s to %d\n", 
					funcName, histNames[i], KW_START_BYTE, objStart+1, histNames[i], KW_BYTES, objSize);
			if (!updateIsis3HistoryStartAndSize(root, objStart+1, objSize)){
				fprintf(stderr, "%s: Failed updating %s.%s to %d and %s.%s to %d\n",
					funcName, histNames[i], KW_START_BYTE, objStart+1, histNames[i], KW_BYTES, objSize);
			}
		}
	}

	return rc;
}


static Var * 
do_writeISIS3(Var *obj, char *ISIS3_filename)
{

	FILE *fp = NULL;
	Var *objCopy = NULL;
	size_t labelSize = 0;
	size_t objStart = 0, objSize = 0;

	if ((fp = fopen(ISIS3_filename, "wb+")) == NULL) {
		fprintf(stderr, "Unable to open file: %s\n", ISIS3_filename);
		return NULL;
	}

	objCopy = V_DUP(obj);
	updateIsis3Struct(objCopy);
	writeIsis3Lbl(objCopy, fp);

	// get the file size, pad by some amount to get label size
	labelSize = ftell(fp);
	//labelSize = ((int)(labelSize / 1024.0 + 4.5))*1024;
	labelSize = 65536; // ISIS3 utilities fail if label size is small - 65536 is the nominal value seen in examples
	if (fseek(fp, labelSize, SEEK_SET) < 0){ // position ot the end of label
		fprintf(stderr, "Unable to seek to offset %ld in file \"%s\". Cause: %s\n", labelSize, ISIS3_filename, strerror(errno));
	}
	if (VERBOSE > 3)
		fprintf(stderr, "Updating Label.Bytes to %d\n", labelSize);
	if (!updateLabelSize(objCopy, labelSize)){
		fprintf(stderr, "Failed updating Label.Bytes to %d\n", labelSize);
	}

	// TODO write data for all objects retaining offsets and sizes
	
	// write core and update its start and size in the label structure
	objStart = ftell(fp);
	writeIsis3CoreData(objCopy, fp, ISIS3_filename);
	objSize = ftell(fp) - objStart;
	if (VERBOSE > 3)
		fprintf(stderr, "Updating Core.StartByte to %d\n", objStart+1);
	if (!updateIsis3CoreStartAndSize(objCopy, objStart+1, objSize)){
		fprintf(stderr, "Failed updating Core.StartByte to %d\n", objStart+1);
	}

	// write each table updating its start in the label structure
	writeIsis3Tbls(objCopy, fp, ISIS3_filename);

	// write the history object
	writeIsis3History(objCopy, fp, ISIS3_filename);

	// write the original label object
	writeIsis3OrgLbl(objCopy, fp, ISIS3_filename);

	// rewind file to overwrite the label with updated start and size values of objects
	rewind(fp);

	// rewrite label with upated start and size values
	writeIsis3Lbl(objCopy, fp);

	fclose(fp);

	// release space allocated for dupliate struct
	mem_claim(objCopy);
	free_var(objCopy);

	return NULL;
}

Var *
ReadISIS3(vfuncptr func, Var * arg)
{
	Var *fn = NULL;
	char *filename = NULL;
	int data = 1;  // parse the cube
	int use_names = 0; // reverse name and info if 1
	int use_units = 0; // use the units field if 1
	int include_tables = 0;
	int include_original_label = 0;
	int mimic_io_module = 0;
	int i;

	/*
	 * If the user inputs load_isis3() or load_ISIS3()
	 * with empty paren's, bail out
	 */

	if (arg == NULL) {
		parse_error(
				"No parameter list supplied--must at least supply an input file name.\n");
		return (NULL);
	}

	Alist alist[8];
	alist[0] = make_alist("filename", ID_UNK, NULL, &fn);
	alist[1] = make_alist("data", INT, NULL, &data);
	alist[2] = make_alist("use_names", INT, NULL, &use_names);
	alist[3] = make_alist("use_units", INT, NULL, &use_units);
	alist[4] = make_alist("incl_tables", INT, NULL, &include_tables);
	alist[5] = make_alist("incl_orglbl", INT, NULL, &include_original_label);
	alist[6] = make_alist("mimic_io_module", INT, NULL, &mimic_io_module);
	alist[7].name = NULL;

	if (parse_args(func, arg, alist) == 0) {
		return (NULL);
	}

	/* Handle loading many filenames */
	if (V_TYPE(fn) == ID_TEXT) {
		Var *s = new_struct(V_TEXT(fn).Row);
		for (i = 0; i < V_TEXT(fn).Row; i++) {
			filename = strdup(V_TEXT(fn).text[i]);
			Var *t = do_loadISIS3(func, filename, data, use_names, use_units, include_tables, include_original_label, mimic_io_module);
			if (t) {
				(s, filename, t);
			}
		}
		if (get_struct_count(s)) {
			return (s);
		} else {
			free_struct(s);
			return (NULL);
		}
	} else if (V_TYPE(fn) == ID_STRING) {
		filename = V_STRING(fn);
		return (do_loadISIS3(func, filename, data, use_names, use_units, include_tables, include_original_label, mimic_io_module));
	} else {
		parse_error("Illegal argument to function %s(%s), expected STRING",
				func->name, "filename");
		return (NULL);
	}
}



// TODO handle array followed by units
/* Read a parameter = value label line. The line can span multiple text lines, e.g.
 * for arrays and such.
 */
static int
read_pvl_line(FILE *fp, char *line, long file_limit){
	int c, cc;
	int i = 0;
	int inquotes = 0, paren_count = 0;
	int inescape = 0, continued = 0;

	if (feof(fp) || (file_limit >= 0 && ftell(fp) >= file_limit)){
		return 0;
	}

	while((file_limit < 0 || (file_limit >= 0 && ftell(fp) < file_limit)) && (c = fgetc(fp))){
		if (isprint(c)){
			if (continued && isspace(c)){
				// skip spaces at the start of continued lines
			}
			else {
				line[i++] = c;
				continued = 0;
			}

			switch(c){
			case '"': inquotes = (!inescape)? !inquotes: inquotes; break; // flip whether we are in quotes
			case '(': paren_count += (!inquotes)? 1: 0; break;
			case ')': paren_count -= (!inquotes)? 1: 0; break;
			default:  break;
			}

			inescape = (!inescape && c == '\\')? 1: 0; // used for next char
		}
		else if (c == '\n' || c == '\r'){
			int val_continued = 0;

			if (!(inquotes || paren_count > 0)){
				int j=i;
				if (line[j-1] == '-'){
					// not in quotes or parens, but encounter a continuation mark '-' at the end of line
					// remove '-' that's already appended to the line
					i--;
					val_continued = 1;
				}
				else {
					line[i++] = c;
				}
			}
			else {
				int j=i;
				while(j>=0 && isspace(line[j])){
					j--;
				}
				if (j<0 || line[j] != '-'){
					line[i++] = ' ';
				}
			}

			cc = fgetc(fp);
			if ((c == '\n' && cc == '\r') || (c == '\r' && cc == '\n')){
				if (!(inquotes || paren_count > 0 || val_continued)){
					line[i++] = cc;
				}
			}
			else {
				ungetc(cc, fp);
			}

			if (!(inquotes || paren_count > 0 || val_continued)){
				continued = 0;
				break; // newline outside of string or parenthesized expression or unquoted / non-parenthesized value line ending in "-" terminates the current param = value line
			}
			else {
				continued = 1;
			}
		}
		else {
			ungetc(c, fp);
			break;
		}
	}

	line[i] = '\0';

	return 1;
}

static int
split_str(char *str, const char *delim, int *count, char ***pcs){
	int n = 0;
	char *tok = NULL;

	*count = 0;
	*pcs = NULL;
	while(tok = strtok(str, delim)){
		str = NULL;
		*pcs = (char **)realloc(*pcs, (*count + 1)*sizeof(char **));
		if (*pcs == NULL){
			fprintf(stderr,"split_str(): ERROR! Unable to realloc %ld bytes. Stopping early.\n", (*count + 1)*sizeof(char **));
			break;
		}
		(*pcs)[(*count) ++] = tok;
	}

	return *count;
}

static char *
buildName(Var *s, const char *str){
	char *name;
	char *fixedName;
	
	name = (char *)alloca(strlen(str)+1);
	strcpy(name, str);
	trim(name, "\"");
	name = gen_next_unused_name_instance(name, s, 1);
	fixedName = fix_name(name,0);
	free(name);

	return fixedName;
}

static int
atomicValType(const char *val, long *i, double *d, char **str){
	int n = strlen(val);
	int val_type = 0;
	char *local_val;
	char *end;
	
	strcpy(local_val = (char *)alloca(strlen(val)+1), val);
	trim(local_val, NULL);

	*i = strtol(local_val, &end, 10);
	if (val_type == 0 && (local_val+n) == end){
		if (*i > MAXINT || *i < MININT){
			val_type = 2;
		}
		else {
			val_type = 1;
		}
	}

	*d = strtod(local_val, &end);
	if (val_type == 0 && (local_val+n) == end){
		val_type = 3;
	}

	*str = val;
	if (val_type == 0){
		val_type = 4;
	}

	return val_type;
}

static Var *
parseAtomicVal(const char *val){
	double d = 0;
	long i = 0;
	char *str = NULL;
	Var *v = NULL;
	
	switch(atomicValType(val, &i, &d, &str)){
	case 1: v = newInt(i); break;
	case 2: v = newLong(i); break;
	case 3: v = newDouble(d); break;
	case 4: v = newString(strdup(str)); break;
	}

	return v;
}

// TODO handle units after array
static Var *
parse1dArrayVal(const char *val_str){
	char *str;
	int npcs = 0;
	char **pcs = NULL;
	int max_type = 1, val_type;
	int i;
	int *iarray;
	long *larray;
	double *darray;
	char **sarray;
	Var *v = NULL;

	// TODO extract the units first then process the rest as an array

	strcpy(str = (char *)alloca(strlen(val_str)+1), val_str);
	split_str(str, "(),", &npcs, &pcs);

	iarray = (int *)calloc(npcs, sizeof(int *));
	larray = (long *)calloc(npcs, sizeof(long *));
	darray = (double *)calloc(npcs, sizeof(double *));
	sarray = (char **)calloc(npcs, sizeof(char *));

	for(i=0; i<npcs; i++){
		trim(pcs[i], NULL);
		val_type = atomicValType(pcs[i], &larray[i], &darray[i], &sarray[i]);
		max_type = (val_type > max_type)? val_type: max_type;
	}

	switch(max_type){
	case 1:
		for(i=0; i<npcs; i++){
			iarray[i] = larray[i];
		}
		free(larray);
		free(darray);
		free(sarray);
		v = newVal(BSQ, npcs, 1, 1, INT, iarray);
		break;
	case 2:
		free(iarray);
		free(darray);
		free(sarray);
		v = newVal(BSQ, npcs, 1, 1, LONG, larray);
		break;
	case 3:
		free(iarray);
		free(larray);
		free(sarray);
		v = newVal(BSQ, npcs, 1, 1, DOUBLE, darray);
		break;
	case 4:
		free(iarray);
		free(larray);
		free(darray);
		for(i=0; i<npcs; i++){
			sarray[i] = strdup(sarray[i]);
		}
		v = newText(npcs, sarray);
		break;
	}

	return v;
}

/**
 * Remove unit part from the input str by putting a '\0' at the
 * unit '<'. The unit part is trimmed of '<>' and spaces and returned.
 * If no units, NULL is returned.
 */
static char *
removeUnits(char *str){
	char *right = strrchr(str, '>');
	char *left = strrchr(str, '<');

	if (left != NULL && right != NULL && left < right){
		/* we have: value <unit> */
		*left = '\0';
		left++;

		trim(left, "<> ");

		return left;
	}

	return NULL;
}

static Var *
parseAndAddKeyVal(Var *root, const char *key_str, const char *val_str, int add_units){
	Var *v = NULL;
	char *str;
	int npcs = 0, i;
	char **pcs = NULL;
	char *key_units = NULL;
	char *key = NULL;
	char *units = NULL;
	
	strcpy(key = (char *)alloca(strlen(key_str)+10), key_str);
	if (key_str[0] == '^'){
		sprintf(key, "%s%s", PFX_PTR, &key_str[1]);
	}

	strcpy(str = (char *)alloca(strlen(val_str)+1), val_str);
	trim(str, NULL);

	if (str[0] == '"'){
		/* string value, remove double quotes and add */
		trim(str, "\"");
		add_struct(root,strdup(key),v=newString(strdup(str)));
	}
	else if (str[0] == '('){
		/* array of values optionally followed by <unit> */
		units = removeUnits(str);
		add_struct(root,strdup(key),v=parse1dArrayVal(trim(str,NULL)));

		if (units != NULL && add_units){
			/* we have: (array) <unit> */
			key_units = strdup(buildUnitKey(key));
			add_struct(root,key_units,newString(strdup(trim(units,NULL))));
		}
	}
	else {
		/* value optionally follwed by <unit> */
		units = removeUnits(str);
		add_struct(root,strdup(key),v=parseAtomicVal(trim(str,NULL)));

		if (units != NULL && add_units){
			/* we have: value <unit> */
			key_units = strdup(buildUnitKey(key));
			add_struct(root,key_units,newString(strdup(trim(units,NULL))));
		}
	}
	
	return v;
}

static const char *
getStrKeyValFromStruct(Var *s, const char *key, const char *notFoundVal){
	Var *e = NULL;
	find_struct(s,key,&e);
	return e != NULL? V_STRING(e): notFoundVal;
}

static int
getIntKeyValFromStruct(Var *s, const char *key, const int notFoundVal){
	Var *e = NULL;
	find_struct(s,key,&e);
	return e != NULL? V_INT(e): notFoundVal;
}

static long
getLongKeyValFromStruct(Var *s, const char *key, const long notFoundVal){
	Var *e = NULL;
	find_struct(s,key,&e);
	return e != NULL? V_LONG(e): notFoundVal;
}

static double
getDblKeyValFromStruct(Var *s, const char *key, const double notFoundVal){
	Var *e = NULL;
	find_struct(s,key,&e);
	return e != NULL? V_DOUBLE(e): notFoundVal;
}

iom_edf
iomConvertIsis3Type(const char *type, const char *byteOrder, int *isText)
{
    int format = iom_EDF_INVALID; /* Assume invalid format to start with */
    
	if (strcmp(type,KW_TYPE_UBYTE) == 0){
		format = strcmp(byteOrder,KW_VAL_MSB) == 0? iom_MSB_INT_1: iom_LSB_INT_1;
	}
	else if (strcmp(type,KW_TYPE_SWORD) == 0 || strcmp(type,KW_TYPE_UWORD) == 0){
		format = strcmp(byteOrder,KW_VAL_MSB) == 0? iom_MSB_INT_2: iom_LSB_INT_2;
	}
	else if (strcmp(type,KW_TYPE_INT) == 0 || strcmp(type,KW_TYPE_SINT) == 0 || strcmp(type,KW_TYPE_UINT) == 0){
		format = strcmp(byteOrder,KW_VAL_MSB) == 0? iom_MSB_INT_4: iom_LSB_INT_4;
	}
	else if (strcmp(type,KW_TYPE_REAL) == 0){
		format = strcmp(byteOrder,KW_VAL_MSB) == 0? iom_MSB_IEEE_REAL_4: iom_LSB_IEEE_REAL_4;
	}
	else if (strcmp(type,KW_TYPE_DOUBLE) == 0){
		format = strcmp(byteOrder,KW_VAL_MSB) == 0? iom_MSB_IEEE_REAL_8: iom_LSB_IEEE_REAL_8;
	}
	else if (strcmp(type,KW_TYPE_TEXT) == 0){
		// should be handled elsewhere
		if (isText != NULL){
			*isText = 1;
		}
	}
    return(format);
}

static int
readTiledData(FILE *fp, int bytes_per_sample, int samples, int lines, int bands, int tile_width, int tile_height, char **output){
	int x = samples, y = lines, z = bands;
	int x_tiles, y_tiles;
	size_t buffer_size = (size_t) tile_width * (size_t) tile_height;
	size_t data_size = (size_t) x * (size_t) y * (size_t) z;
	char *buffer = NULL, *data = NULL;
	int tile_x, tile_y, tile_z, row_stride, tile_row_bytes, x_tile_idx, y_tile_idx, i;
	size_t src_offset, dest_offset;
	int actual_tile_width, actual_tile_height;
	int read_successful;
	int rc = 1;

    x_tiles = (int) ceil(x / (double) tile_width); // number of tiles in x-direction
    y_tiles = (int) ceil(y / (double) tile_height); // number of tiles in y-direction

    row_stride = x * bytes_per_sample; // Assume BSQ: each band will be read separately

	tile_row_bytes = tile_width * bytes_per_sample;

    buffer = (unsigned char *) malloc(buffer_size * (size_t)bytes_per_sample);
    data = (unsigned char *) malloc(data_size * (size_t)bytes_per_sample);

    if (data == NULL || buffer == NULL) {
		fprintf(stderr, "Unable to allocate %ld bytes.\n", (buffer_size + data_size)* (size_t)bytes_per_sample);
		if (buffer) free(buffer);
		if (data) free(data);
		return 0;
    }

	read_successful = 1;

	for (tile_z = 0; read_successful && tile_z < z; tile_z++) {

		for (tile_y = 0; read_successful && tile_y < y; tile_y += tile_height) {
			y_tile_idx = tile_y / tile_height;
			actual_tile_height = MIN(y, tile_y + tile_height) - tile_y;

			for (tile_x = 0; read_successful && tile_x < x; tile_x += tile_width) {
				x_tile_idx = tile_x / tile_width;
				actual_tile_width = MIN(x, tile_x + tile_width) - tile_x;

				read_successful = (fread(buffer, bytes_per_sample, buffer_size, fp) == buffer_size);
				if (read_successful){
					for (i = 0; i < actual_tile_height; i++) {
						src_offset = i * (size_t)tile_row_bytes;
						dest_offset = (tile_z * y * (size_t)row_stride) // (a) point to start of band
							+ (tile_y * (size_t)row_stride) // (b) point to the start of the rows covering tile_y within (a)
							+ (x_tile_idx * (size_t)tile_row_bytes)  // (c) point to the start of columns covering tile_x within (b)
							+ (i * (size_t)row_stride);  // (d) point to the start of row within tile_x, tile_y

						memcpy(data + dest_offset, buffer + src_offset, actual_tile_width * bytes_per_sample);
					}
				}
			}
		}
	}

	if (!read_successful){
		rc = -1;
	}

	free(buffer);
	*output = data;

	return rc;
}

// assumes data is in BSQ org
static int
writeTiledData(FILE *fp, int bytes_per_sample, int samples, int lines, int bands, int tile_width, int tile_height, const char *data){
	int x = samples, y = lines, z = bands;
	int x_tiles, y_tiles;
	size_t buffer_size = (size_t) tile_width * (size_t) tile_height;
	size_t data_size = (size_t) x * (size_t) y * (size_t) z;
	char *buffer = NULL;
	int tile_x, tile_y, tile_z, row_stride, tile_row_bytes, x_tile_idx, y_tile_idx, i;
	size_t src_offset, dest_offset;
	int actual_tile_width, actual_tile_height;
	int write_successful;
	int rc = 1;

    x_tiles = (int) ceil(x / (double) tile_width); // number of tiles in x-direction
    y_tiles = (int) ceil(y / (double) tile_height); // number of tiles in y-direction

    row_stride = x * bytes_per_sample; // Assume BSQ: each band will be read separately

	tile_row_bytes = tile_width * bytes_per_sample;

    buffer = (unsigned char *) malloc(buffer_size * (size_t)bytes_per_sample);

    if (buffer == NULL) {
		fprintf(stderr, "Unable to allocate %ld bytes.\n", (buffer_size)* (size_t)bytes_per_sample);
		if (buffer) free(buffer);
		return 0;
    }

	write_successful = 1;

	for (tile_z = 0; write_successful && tile_z < z; tile_z++) {

		for (tile_y = 0; write_successful && tile_y < y; tile_y += tile_height) {
			y_tile_idx = tile_y / tile_height;
			actual_tile_height = MIN(y, tile_y + tile_height) - tile_y;

			for (tile_x = 0; write_successful && tile_x < x; tile_x += tile_width) {
				x_tile_idx = tile_x / tile_width;
				actual_tile_width = MIN(x, tile_x + tile_width) - tile_x;

				for (i = 0; i < actual_tile_height; i++) {
					dest_offset = i * (size_t)tile_row_bytes;
					src_offset = (tile_z * y * (size_t)row_stride) // (a) point to start of band
						+ (tile_y * (size_t)row_stride) // (b) point to the start of the rows covering tile_y within (a)
						+ (x_tile_idx * (size_t)tile_row_bytes)  // (c) point to the start of columns covering tile_x within (b)
						+ (i * (size_t)row_stride);  // (d) point to the start of row within tile_x, tile_y

					memcpy(buffer + dest_offset, data + src_offset, actual_tile_width * bytes_per_sample);
				}
				write_successful = (fwrite(buffer, bytes_per_sample, buffer_size, fp) == buffer_size);
			}
		}
	}

	if (!write_successful){
		rc = -1;
	}

	free(buffer);
	return rc;
}


static double
getDnAsDouble(iom_idf iFmt, const char *data){
	double dn;

	switch(iFmt){
	case iom_BYTE:  dn = (double)*(const unsigned char *)(data); break;
	case iom_SHORT: dn = (double)*(const short *)(data); break;
	case iom_FLOAT: dn = (double)*(const float *)(data); break;
	default:        dn = 0; break;
	}

	return dn;
}

static double
getDnAsDoubleAlt(iom_idf iFmt, const char *data){
	double dn;
	unsigned char uc;
	short s;
	float f;

	switch(iFmt){
	case iom_BYTE:  memcpy(&uc, data, sizeof(uc)); dn = (double)uc; break;
	case iom_SHORT: memcpy(&s,  data, sizeof(s));  dn = (double)s; break;
	case iom_FLOAT: memcpy(&f,  data, sizeof(f));  dn = (double)f; break;
	default:        dn = 0; break;
	}

	return dn;
}

static char *
buildDataFileName(Var *coreObj, const char *objType, const char *lblFileName){
	char ptrKey[1024];
	char *tmpStr = NULL, *dataFileName = NULL;
	const char *detachedDataFileName;

	sprintf(ptrKey, "%s%s", PFX_PTR, objType);
	detachedDataFileName = getStrKeyValFromStruct(coreObj, ptrKey, NULL);

	tmpStr = alloca(strlen(lblFileName)+1);
	strcpy(tmpStr, lblFileName);
	if (detachedDataFileName == NULL){
		dataFileName = tmpStr;
	}
	else{
		dataFileName = (char *)alloca(strlen(lblFileName)+strlen(detachedDataFileName)+10);
		sprintf(dataFileName, "%s/%s", dirname(tmpStr), detachedDataFileName);
	}

	return strdup(dataFileName);
}

// TODO check existance of needed keywords before jumping into using them

static Var *
readIsis3Core(Var *coreObj, const char *lblFileName){
	int samples = 0, lines = 0, bands = 0;
	int isTiled = 0, tLines = 0, tSamples = 0;
	double base = 0, multiplier = 1.0;
	Var *eDims = NULL, *ePixels = NULL, *e = NULL;
	const char *orgStr = NULL, *fmtStr = NULL, *typeStr = NULL, *byteOrderStr = NULL;
	//const char *detachedDataFileName = NULL;
	int org;
	long startByte = 0;
	iom_edf eFmt;
	iom_idf iFmt, oiFmt;
	fpos_t savedPos;
	FILE *dfp;
	char *dataFileName = NULL; 
	int rc;
	char *data = NULL;
	Var *result = NULL;
	size_t dataSize;
	ssize_t ii;
	//char *tmpStr; 


	//detachedDataFileName = getStrKeyValFromStruct(coreObj, "ptr_to_Core", NULL);
	startByte = getLongKeyValFromStruct(coreObj, KW_START_BYTE, 1); // byte offsets are 1-based in ISIS3 labels
	fmtStr = getStrKeyValFromStruct(coreObj, KW_FORMAT, NULL);
	tSamples = getIntKeyValFromStruct(coreObj, KW_TSAMPLES, 0);
	tLines = getIntKeyValFromStruct(coreObj, KW_TLINES, 0);
	if (fmtStr == NULL){
		fmtStr = (tSamples > 0 && tLines > 0)? KW_FMT_TILE: KW_FMT_BSQ;
	}
	org = BSQ;

	find_struct(coreObj,KW_GRP_DIMS,&eDims);
	if (eDims == NULL){
		fprintf(stderr, "readIsis3Core(): Cannot find \"Dimensions\" group in \"Core\"\n");
		return 0;
	}
	samples = getIntKeyValFromStruct(eDims,KW_SAMPLES,0);
	lines = getIntKeyValFromStruct(eDims,KW_LINES,0);
	bands = getIntKeyValFromStruct(eDims,KW_BANDS,0);
	dataSize = (size_t)samples*(size_t)lines*(size_t)bands;

	find_struct(coreObj,KW_GRP_PIXELS,&ePixels);
	if (ePixels == NULL){
		fprintf(stderr, "Cannot find \"Pixels\" group in \"Core\"\n");
		return 0;
	}

	typeStr = getStrKeyValFromStruct(ePixels, KW_TYPE, NULL);
	byteOrderStr = getStrKeyValFromStruct(ePixels, KW_BYTE_ORDER, KW_VAL_LSB);
	base = getDblKeyValFromStruct(ePixels,KW_BASE,0.0);
	multiplier = getDblKeyValFromStruct(ePixels,KW_MULTIPLIER,1.0);

	eFmt = iomConvertIsis3Type(typeStr, byteOrderStr, NULL);
	//iFmt = iom_Eformat2Iformat(eFmt);

	/* data file could be detached - determine the file we need to read the data */
	dataFileName = buildDataFileName(coreObj, KW_OBJ_CORE, lblFileName);

	if (VERBOSE > 2)
		fprintf(stderr, "Reading Core from \"%s\" at start byte %d\n", dataFileName, startByte);
	if ((dfp = fopen(dataFileName,"rb")) == NULL){
		fprintf(stderr, "readIsis3Core(): Unable to open file \"%s\" for reading. Cause: %s\n", dataFileName, strerror(errno));
	}
	else {
		if (fseek(dfp, startByte-1, SEEK_SET) != 0){
			fprintf(stderr, "readIsis3Core(): Unable to seek to offset %ld in file \"%s\". Cause: %s\n", startByte-1, dataFileName, strerror(errno));
		}
		else {
			if (strcmp(fmtStr,KW_FMT_TILE) == 0){
				rc = readTiledData(dfp, iom_NBYTES(eFmt), samples, lines, bands, tSamples, tLines, &data);
				if (rc == 0){
					fprintf(stderr, "readIsis3Core(): Unable to read Core data from \"%s\"\n", dataFileName);
				}
				else if (rc < 0){
					fprintf(stderr, "readIsis3Core(): Partially read Core data from \"%s\"\n", dataFileName);
				}
			}
			else {
				size_t readSize;
				if ((data = (char *)calloc(dataSize, iom_NBYTES(eFmt))) == NULL){
					fprintf(stderr, "readIsis3Core(): ERROR! Unable to allocate %ld bytes.\n", dataSize*iom_NBYTES(eFmt));
					rc = 0;
				}
				else {
					if ((readSize = fread(data, iom_NBYTES(eFmt), dataSize, dfp)) != dataSize){
						fprintf(stderr, "readIsis3Core(): Partially read Core data from \"%s\" (requested: %ld items, read: %ld items)\n",
							dataFileName, dataSize, readSize);
					}
				}
			}
		}

		if (dfp != NULL){
			fclose(dfp);
		}

		// byte-swap and convert to target format -- swap_endian(data,dataSize,iom_NBYTESI(iFmt));
		iFmt =  iom_byte_swap_data(data, dataSize, eFmt);
		
		/* TODO select internal format based on the determined internal format, the base and multiplier */
		if (base != 0.0 && multiplier != 1.0){
			oiFmt = iom_FLOAT;

			if (iom_NBYTESI(iFmt) < iom_NBYTESI(oiFmt)){
				data = realloc(data, dataSize * iom_NBYTESI(oiFmt));
				if (data == NULL){
					fprintf(stderr, "readIsis3Core(): Unable to realloc %ld bytes to %ld bytes\n", dataSize*iom_NBYTESI(iFmt), dataSize*iom_NBYTESI(oiFmt));
				}
				else {
					int inputWordSize = iom_NBYTESI(iFmt);
					int outputWordSize = iom_NBYTESI(oiFmt);
					double dn;
					for(ii=dataSize-1; ii>=0; ii--){
						dn = getDnAsDouble(iFmt, data + ii*inputWordSize);
						dn = dn*multiplier + base;
						*(float *)(data + ii*outputWordSize) = dn;
					}
				}
			}
			else {
				int inputWordSize = iom_NBYTESI(iFmt);
				int outputWordSize = iom_NBYTESI(oiFmt);
				double dn;
				for(ii=0; ii<dataSize; ii++){
					dn = getDnAsDouble(iFmt, data + ii*inputWordSize);
					dn = dn*multiplier + base;
					*(float *)(data + ii*outputWordSize) = dn;
				}
			}
			iFmt = iom_FLOAT;
		}

		if (data != NULL){
			result = newVal(org, samples, lines, bands, ihfmt2vfmt(iFmt), data);
		}
	}

	if (dataFileName != NULL)
		free(dataFileName);
	

	return result;
}

static struct Isis3Field *
findTblFields(Var *coreObj, int *nFields){
	int i, n, m;
	struct Isis3Field *fields;
	Var *e;
	int byteOffset = 0;
	const char *eFmtStr = NULL;
	const char *byteOrderStr = NULL;
	char *objName = NULL;

	// ByteOrder lives in the top level of table object
	byteOrderStr = getStrKeyValFromStruct(coreObj, KW_BYTE_ORDER, KW_VAL_LSB);

	n = get_struct_count(coreObj);
	fields = (struct Isis3Field *)calloc(n, sizeof(struct Isis3Field));

	// TODO sort fields once field order is added
	m = 0;
	for(i=0; i<n; i++){
		get_struct_element(coreObj, i, &objName, &e);
		if (e == NULL || V_TYPE(e) != ID_STRUCT){
			continue;
		}
		if (strcmp(getStrKeyValFromStruct(e,ISIS3_OBJ_TYPE_KEY, "unknown"),KW_GRP_FIELD) == 0){
			fields[m].objName = objName;
			fields[m].name = getStrKeyValFromStruct(e,KW_NAME,NULL);
			eFmtStr = getStrKeyValFromStruct(e,KW_TYPE,NULL);
			fields[m].isText = 0;
			fields[m].eFmt = iomConvertIsis3Type(eFmtStr,byteOrderStr,&fields[m].isText); // TODO handle text / character fields
			fields[m].itemCount = getIntKeyValFromStruct(e,KW_SIZE,0);
			fields[m].itemSize = iom_NBYTES(fields[m].eFmt);
			fields[m].byteSize = fields[m].itemCount * fields[m].itemSize;
			fields[m].byteOffset = byteOffset;

			byteOffset += fields[m].byteSize;
			m++;
		}
	}

	fields = (struct Isis3Field *)realloc(fields, m*sizeof(struct Isis3Field));
	*nFields = m;

	return fields;
}

static Var *
readIsis3Tbl(Var *coreObj, const char *lblFileName){
	Var *result = NULL;
	long startByte;
	int rows;
	long tblSize;
	int rowSize;
	int nFields = 0;
	char **fieldData = NULL;
	struct Isis3Field *fields = NULL;
	const char *tblName = NULL;
	char *dataFileName = NULL;
	int i,j,k;
	FILE *dfp;
	char *buff = NULL;


	startByte = getLongKeyValFromStruct(coreObj,KW_START_BYTE,1); // byte offsets are 1-based in ISIS3 labels
	tblSize = getIntKeyValFromStruct(coreObj,KW_BYTES,0);
	rows = getIntKeyValFromStruct(coreObj,KW_RECORDS,0);
	tblName = getStrKeyValFromStruct(coreObj,KW_NAME, NULL);
	rowSize = tblSize/rows;

	fields = findTblFields(coreObj, &nFields);

	buff = (char *)calloc(rowSize, sizeof(char));

	// TODO add object nmber and group within object number
	fieldData = (char **)calloc(nFields, sizeof(char **));
	for(i=0; i<nFields; i++){
		fieldData[i] = (char *)calloc(rows, fields[i].byteSize);
	}

	dataFileName = buildDataFileName(coreObj, KW_OBJ_TABLE, lblFileName);

	if (VERBOSE > 2)
		fprintf(stderr, "Reading Table [%s] from \"%s\" at start byte %d\n", tblName, dataFileName, startByte);
	if ((dfp = fopen(dataFileName,"rb")) == NULL){
		fprintf(stderr, "readIsis3Tbl(): Unable to open file \"%s\" for reading. Cause: %s\n", dataFileName, strerror(errno));
	}
	else {
		if (fseek(dfp, startByte-1, SEEK_SET) < 0){
			fprintf(stderr, "readIsis3Tbl(): Unable to seek to offset %ld in file \"%s\". Cause: %s\n", startByte-1, dataFileName, strerror(errno));
		}
		else {

			// read data
			for(j=0; j<rows; j++){
				if (fread(buff, rowSize, 1, dfp) != 1){
					fprintf(stderr, "readIsis3Tbl(): Unable to read row %d of size %d in file \"%s\". Cause: %s\n", j, rowSize, dataFileName, strerror(errno));
					break;
				}
				for(i=0; i<nFields; i++){
					for(k=0; k<fields[i].itemCount; k++){
						memcpy(fieldData[i]+j*fields[i].byteSize+k*fields[i].itemSize, buff+fields[i].byteOffset, fields[i].itemSize);
					}
				}
			}
		}
	}

	if (dfp != NULL){
		fclose(dfp);
	}

	// byte swap if needed
	for(i=0; i<nFields; i++){
		fields[i].iFmt = iom_byte_swap_data(fieldData[i], rows*fields[i].byteSize, fields[i].eFmt);
	}

	result = new_struct(nFields);
	for(i=0; i<nFields; i++){
		Var *e = newVal(BSQ, fields[i].itemCount, rows, 1, ihfmt2vfmt(fields[i].iFmt), fieldData[i]);
		add_struct(result, strdup(fields[i].objName), e);
	}

	if (dataFileName != NULL)
		free(dataFileName);

	return result;
}

static Var *
readIsis3OrgLbl(Var *coreObj, const char *lblFileName){
	long startByte = 0;
	int byteSize = 0;
	char *data = NULL;
	char *dataFileName = NULL;
	FILE *dfp = NULL;
	char **pcs = NULL;
	int nPcs = 0;
	Var *result = NULL;
	int i;

	startByte = getLongKeyValFromStruct(coreObj,KW_START_BYTE,1); // byte offsets are 1-based in ISIS3 labels
	byteSize = getIntKeyValFromStruct(coreObj,KW_BYTES,0);

	dataFileName = buildDataFileName(coreObj, KW_OBJ_ORGLBL, lblFileName);

	data = (char *)calloc(byteSize, sizeof(char));

	if (VERBOSE > 2)
		fprintf(stderr, "Reading OriginalLabel from \"%s\" at start byte %d\n", dataFileName, startByte);
	if ((dfp = fopen(dataFileName,"rb")) == NULL){
		fprintf(stderr, "readIsis3OrgLbl(): Unable to open file \"%s\" for reading. Cause: %s\n", dataFileName, strerror(errno));
	}
	else {
		if (fseek(dfp, startByte-1, SEEK_SET) < 0){
			fprintf(stderr, "readIsis3OrgLbl(): Unable to seek to offset %ld in file \"%s\". Cause: %s\n", startByte-1, dataFileName, strerror(errno));
		}
		else {
			if (fread(data, sizeof(char), byteSize, dfp) != byteSize){
				fprintf(stderr, "readIsis3OrgLbl(): Unable to read %d bytes from file \"%s\". Cause: %s\n", byteSize, dataFileName, strerror(errno));
			}
			split_str(data, "\n", &nPcs, &pcs);
			for(i=0; i<nPcs; i++){
				pcs[i] = strdup(pcs[i]);
			}
		}
	}

	if (data != NULL)
		free(data);

	if (dfp != NULL)
		fclose(dfp);

	if (dataFileName != NULL)
		free(dataFileName);

	result = newText(nPcs,pcs==NULL?(char **)calloc(1,sizeof(char **)):pcs);

	return result;
}

static Var *
readIsis3Hist(Var *coreObj, const char *lblFileName, int useNames, int useUnits){
	char *data = NULL;
	long startByte = 0;
	int byteSize = 0;
	char *dataFileName = NULL;
	FILE *dfp = NULL;
	char *path = "histroot";
	int lineNum = 0;
	Var *result = NULL;

	startByte = getLongKeyValFromStruct(coreObj,KW_START_BYTE,1); // byte offsets are 1-based in ISIS3 labels
	byteSize = getIntKeyValFromStruct(coreObj,KW_BYTES,0);

	dataFileName = buildDataFileName(coreObj, KW_OBJ_HISTORY, lblFileName);

	if (VERBOSE > 2)
		fprintf(stderr, "Reading History from \"%s\" at start byte %d\n", dataFileName, startByte);

	if ((dfp = fopen(dataFileName,"rb")) == NULL){
		fprintf(stderr, "readIsis3Hist(): Unable to open file \"%s\" for reading. Cause: %s\n", dataFileName, strerror(errno));
	}
	else {
		if (fseek(dfp, startByte-1, SEEK_SET) < 0){
			fprintf(stderr, "readIsis3Hist(): Unable to seek to offset %ld in file \"%s\". Cause: %s\n", startByte-1, dataFileName, strerror(errno));
		}
		else {
			// traverseIsis3Lbl()
			//while(read_pvl_line(dfp, line)){
			//}
			result = new_struct(0);
			traverseIsis3Lbl(dataFileName, dfp, result, useNames, useUnits, 0, path, &lineNum, (startByte-1+byteSize));
		}
	}

	if (dfp != NULL){
		fclose(dfp);
	}

	if (dataFileName != NULL)
		free(dataFileName);

	return result;
}

static char *
getIsis3StructType(const char *key, const char *val){
	static char isis3StructType[1024];
	char *key_lower;
	char *val_lower;
	
	strcpy(key_lower=(char *)alloca(strlen(key)+1), key);
	lowercase(key_lower);

	strcpy(val_lower=(char *)alloca(strlen(val)+1), val);
	lowercase(val_lower);

	if (strcmp(val,KW_OBJ_TABLE)==0 || strcmp(val,KW_OBJ_HISTORY)==0 || strcmp(val,KW_GRP_FIELD)==0){
		strcpy(isis3StructType,val_lower);
	}
	else {
		strcpy(isis3StructType,key_lower);
	}

	return isis3StructType;
}

static void
findIsis3ObjsByElementName0(Var *objRoot, const char *objRootName, Var *objParent, const char *elementName, Var ***found,  Var ***foundParents, int *nFound){
	const char *funcName = "findIsis3ObjsByElementName0()";
	int count, j;
	Var *e;
	char *name;

	if (V_TYPE(objRoot) == ID_STRUCT){
    	count = get_struct_count(objRoot);
    	for (j = 0; j < count; j++) {
			get_struct_element(objRoot, j, &name, &e);
			if (name != NULL && strcmp(name, elementName) == 0){
					*found = (Var **)realloc(*found, (1+*nFound) * sizeof(Var *));
					*foundParents = (Var **)realloc(*foundParents, (1+*nFound) * sizeof(Var *));
					(*found)[*nFound] = e;
					(*foundParents)[*nFound] = objParent;
					(*nFound)++;
					if (VERBOSE > 4){
						fprintf(stderr,"%s: Found %d \"%s\" element (%p) with parent %p\n",
							funcName, *nFound, elementName, e, objParent);
					}
			}
			if (V_TYPE(e) == ID_STRUCT){
				findIsis3ObjsByElementName0(e,name,objRoot,elementName,found,foundParents,nFound);
			}
		}
	}
}

static void
findIsis3ObjsByElementName(Var *objRoot, const char *elementName, Var ***found,  Var ***foundParents, int *nFound){
	*found = NULL;
	*foundParents = NULL;
	*nFound = 0;
	findIsis3ObjsByElementName0(objRoot,NULL,NULL,elementName,found,foundParents,nFound);
}

static int
findFirstIsis3ObjByElementName(Var *objRoot, const char *elementName, Var **found,  Var **foundParent){
	Var **_found = NULL;
	Var **_foundParent = NULL;
	int nFound = 0;

	findIsis3ObjsByElementName(objRoot, elementName, &_found, &_foundParent, &nFound);

	if (nFound > 0){
		*found = _found[0];
		*foundParent = _foundParent[0];

		free(_found);
		free(_foundParent);
	}

	return nFound;
}

static void
findIsis3ObjsContainingKeyVal0(Var *objRoot, const char *objRootName, Var *objParent, const char *findKeyName, const char *findKeyVal, Var ***found, char ***foundNames, Var ***foundParents, int *nFound){
	const char *funcName = "findIsis3ObjsContainingKeyVal0()";
	int count, j;
	Var *e;
	char *name;

	if (V_TYPE(objRoot) == ID_STRUCT){
    	count = get_struct_count(objRoot);
    	for (j = 0; j < count; j++) {
			get_struct_element(objRoot, j, &name, &e);
			if (name != NULL && strcmp(name, findKeyName) == 0){
				if (strcmp(V_STRING(e),findKeyVal) == 0){
					*found = (Var **)realloc(*found, (1+*nFound) * sizeof(Var *));
					*foundNames = (char **)realloc(*foundNames, (1+*nFound) * sizeof(char *));
					*foundParents = (Var **)realloc(*foundParents, (1+*nFound) * sizeof(Var *));
					(*found)[*nFound] = objRoot;
					(*foundNames)[*nFound] = objRootName;
					(*foundParents)[*nFound] = objParent;
					(*nFound)++;
					if (VERBOSE > 4){
						fprintf(stderr,"%s: Found %d \"%s=%s\" object (%p) named \"%s\" with parent %p\n",
							funcName, *nFound, findKeyName, findKeyVal, objRoot, objRootName, objParent);
					}
				}
			}
			else if (V_TYPE(e) == ID_STRUCT){
				findIsis3ObjsContainingKeyVal0(e,name,objRoot,findKeyName,findKeyVal,found,foundNames,foundParents,nFound);
			}
		}
	}
}

static void
findIsis3ObjsByType0(Var *objRoot, const char *objRootName, Var *objParent, const char *objType, Var ***found, char ***foundNames, Var ***foundParents, int *nFound){
	findIsis3ObjsContainingKeyVal0(objRoot, objRootName, objParent, ISIS3_OBJ_TYPE_KEY, objType, found, foundNames, foundParents, nFound);
}

static void
findIsis3ObjsByType(Var *objRoot, const char *objType, Var ***found, char ***foundNames, Var ***foundParents, int *nFound){
	*found = NULL;
	*foundNames = NULL;
	*foundParents = NULL;
	*nFound = 0;
	findIsis3ObjsByType0(objRoot,NULL,NULL,objType,found,foundNames,foundParents,nFound);
}

static int
findFirstIsis3ObjByType(Var *objRoot, const char *objType, Var **found, char **foundName, Var **foundParent){
	Var **_found = NULL;
	Var **_foundParent = NULL;
	char **_foundName = NULL;
	int nFound = 0;

	findIsis3ObjsByType(objRoot, objType, &_found, &_foundName, &_foundParent, &nFound);

	if (nFound > 0){
		*found = _found[0];
		*foundName = _foundName[0];
		*foundParent = _foundParent[0];

		free(_found);
		free(_foundName);
		free(_foundParent);
	}

	return nFound;
}

static void
findIsis3ObjsByIsisStructType(Var *objRoot, const char *isisStructType, Var ***found, char ***foundNames, Var ***foundParents, int *nFound){
	*found = NULL;
	*foundNames = NULL;
	*foundParents = NULL;
	*nFound = 0;
	findIsis3ObjsContainingKeyVal0(objRoot,NULL,NULL,ISIS3_STRUCT_TYPE_KEY,isisStructType,found,foundNames,foundParents,nFound);
}
static int
findFirstIsis3ObjByIsisStructType(Var *objRoot, const char *isisStructType, Var **found, char **foundName, Var **foundParent){
	Var **_found = NULL;
	Var **_foundParent = NULL;
	char **_foundName = NULL;
	int nFound = 0;

	findIsis3ObjsByIsisStructType(objRoot, isisStructType, &_found, &_foundName, &_foundParent, &nFound);

	if (nFound > 0){
		*found = _found[0];
		*foundName = _foundName[0];
		*foundParent = _foundParent[0];

		free(_found);
		free(_foundName);
		free(_foundParent);
	}

	return nFound;
}



static Var *
traverseIsis3Lbl(const char *lbl_file_name, FILE *fp, Var *root, int use_names, int use_units, int read_data, const char *path, int *line_num, long file_limit){
	char line[4096];
	Var *e = NULL;
	Var *e_name = NULL;
	char *name = NULL;
	char *line_copy = NULL;
	int npcs = 0, i;
	char **pcs = NULL;
	char *sub_path = NULL;
	Var *data_var = NULL;

	while(read_pvl_line(fp, line, file_limit)){
		(*line_num)++;
		//printf("line: %d :: %s", *line_num, line);

		//if (strlen(line) == 0){
		//	break;
		//}
		trim(line, NULL);

		//split_string(line_copy = strdup(line), &npcs, &pcs, "=");
		split_str(line_copy = strdup(line), "=", &npcs, &pcs);
		for(i=0; i<npcs; i++){
			trim(pcs[i], NULL);
		}
		
		if (npcs > 1){ // all label lines except its end has a key = value form
			if (strcmp(pcs[0],KW_OBJ) == 0 || strcmp(pcs[0],KW_GRP) == 0){
				sprintf(sub_path = malloc(strlen(path)+strlen(".")+strlen(pcs[1])+1), "%s.%s", path, pcs[1]);
				e = new_struct(0);
				traverseIsis3Lbl(lbl_file_name, fp, e, use_names, use_units, read_data, sub_path, line_num, file_limit);
				add_struct(e,strdup(ISIS3_OBJ_TYPE_KEY), newString(strdup(pcs[1])));
				add_struct(e,strdup(ISIS3_STRUCT_TYPE_KEY), newString(strdup(getIsis3StructType(pcs[0],pcs[1]))));
				find_struct(e,KW_NAME,&e_name);
				name = buildName(root, use_names && e_name != NULL? V_STRING(e_name): pcs[1]);
				add_struct(root,name,e);
				if (VERBOSE > 3)
					fprintf(stderr, "%s %s [%s] (%p) added to %s (%p)\n", pcs[0], pcs[1], name, e, path, root);
				if (read_data && strcmp(pcs[0],KW_OBJ) == 0){
					data_var = NULL;
					if (strcmp(pcs[1],KW_OBJ_CORE) == 0){
						data_var = readIsis3Core(e, lbl_file_name);
					}
					else if (strcmp(pcs[1],KW_OBJ_TABLE) == 0){
						data_var = readIsis3Tbl(e, lbl_file_name);
					}
					else if (strcmp(pcs[1],KW_OBJ_LABEL) == 0){
						// already read by traverseIsis3Lbl
					}
					else if (strcmp(pcs[1],KW_OBJ_ORGLBL) == 0){
						data_var = readIsis3OrgLbl(e, lbl_file_name);
					}
					else if (strcmp(pcs[1],KW_OBJ_HISTORY) == 0){
						data_var = readIsis3Hist(e, lbl_file_name, use_names, use_units);
					}
					if (data_var != NULL){
						add_struct(e, strdup("data"), data_var);
					}
				}
				free(sub_path);
			}
			else {
				parseAndAddKeyVal(root,pcs[0],pcs[1],use_units);
				//fprintf(stderr, "Element %s = %s added to %s\n", pcs[0], pcs[1], path);
			}
		}

		free(line_copy);
		free(pcs);

		// end of object / label
		if (strcmp(line, KW_END) == 0 || strcmp(line, KW_OBJ_END) == 0 || strcmp(line, KW_GRP_END) == 0){
			break;
		}
	}

	return(root);
}

static void
removeIsis3ObjsFromStruct(Var *root, const char *objType){
	Var **found_objs = NULL;
	char **found_names = NULL;
	Var **found_obj_parents = NULL;
	int n_found = 0;
	int i = 0;
	Var *e = NULL;

	findIsis3ObjsByType(root,objType,&found_objs,&found_names,&found_obj_parents,&n_found);
	if (VERBOSE > 3){
		fprintf(stderr, "Found %d %s objects.\n", n_found, objType);
	}

	for(i=0; i<n_found; i++){
		if (found_obj_parents[i] != NULL && found_names[i] != NULL){
			if (VERBOSE > 3){
				fprintf(stderr, "Removing %s object named %s\n", objType, found_names[i]);
			}
			e = remove_struct_by_key(found_obj_parents[i], found_names[i]);
			if (e != NULL){
				mem_claim(e);
				free_var(e);
			}
		}
	}

	if (n_found > 0){
		free(found_objs);
		free(found_names);
		free(found_obj_parents);
	}
}

static int
moveIsis3CoreDataToTopLevel(Var *root){
	Var **found_objs = NULL;
	char **found_names = NULL;
	Var **found_obj_parents = NULL;
	int n_found = 0;
	int i = 0;
	Var *e = NULL;
	char *objType = KW_OBJ_CORE;
	char *eName = "data";
	int rc = 0;

	findIsis3ObjsByType(root,objType,&found_objs,&found_names,&found_obj_parents,&n_found);
	if (VERBOSE > 3){
		fprintf(stderr, "Found %d %s objects.\n", n_found, objType);
	}

	if (n_found > 0){
		if (find_struct(found_objs[0], eName, NULL) >= 0){
			e = remove_struct_by_key(found_objs[0], eName);
			if (e != NULL){
				mem_claim(e);
				add_struct(root, strdup(KW_COREDATA), e);

				rc = 1;
			}
			else {
				if (VERBOSE > 2){
					fprintf(stderr, "moveIsis3CoreDataToTopLevel(): \"%s\" element could not be removed from \"%s\" (%p)\n",
						eName, objType, e);
				}
			}
		}
		else {
			if (VERBOSE > 2){
				fprintf(stderr, "moveIsis3CoreDataToTopLevel(): object type \"%s\" not found\n", objType);
			}
		}

		free(found_objs);
		free(found_names);
		free(found_obj_parents);
	}

	return 0;
}

static int
reorgIsis3HistoryObj(Var *root){
	const char *historyObjType = KW_OBJ_HISTORY;
	const char *dataObjName = "data";
	Var *e = NULL;
	Var *historyObj = NULL, *historyObjParent = NULL;
	char *historyObjName = NULL;
	Var *dataObj = NULL;
	char *eName = NULL;
	char *saveName = NULL;
	int rc = 1;
	int j, n = 0;

	if (findFirstIsis3ObjByType(root,historyObjType,&historyObj,&historyObjName,&historyObjParent)){

		find_struct(historyObj, dataObjName, &dataObj);
		if (dataObj != NULL){
			n = get_struct_count(dataObj);
			for(j=0; j<n; j++){
				get_struct_element(dataObj, j, &eName, &e);
				saveName = strdup(eName);
				e = remove_struct_by_key(dataObj, eName);
				if (e != NULL){
					mem_claim(e);
					add_struct(historyObj, saveName, e);
				}
				else {
					if (VERBOSE > 2){
						fprintf(stderr, "reorgIsis3HistoryObj(): \"%s\" element could not be removed from \"%s\" object (%p)\n",
							saveName, historyObjName, historyObj);
					}
					rc=0;
				}
			}

			e = remove_struct_by_key(historyObj, dataObjName);
			if (e != NULL){
				mem_claim(e);
				free_var(e);
			}
			else {
				if (VERBOSE > 2){
					fprintf(stderr, "reorgIsis3HistoryObj(): \"%s\" element could not be removed from \"%s\" object (%p)\n",
						dataObjName, strdup(historyObjName), historyObj);
				}
				rc=0;
			}
		}
		else {
			if (VERBOSE > 2){
				fprintf(stderr, "reorgisis3HistoryObj(): object \"%s\" not found in \"%s\" object (%p)\n",	
					dataObjName, historyObjName, historyObj);
			}
			rc=0;
		}
	}
	else {
		if (VERBOSE > 2){
			fprintf(stderr, "reorgIsis3HistoryObj(): \"%s\" object not found\n", historyObjType);
		}
		rc = 0;
	}

	return rc;
}

static int
moveIsis3HistoryToCore(Var *root){
	const char *historyObjType = KW_OBJ_HISTORY;
	const char *coreObjType = KW_OBJ_CORE;
	Var *e = NULL;
	Var *historyObj = NULL, *historyObjParent = NULL;
	char *historyObjName = NULL;
	Var *coreObj = NULL, *coreObjParent = NULL;
	char *coreObjName = NULL;
	char *saveHistoryObjName = NULL;
	int rc = 0;

	if (findFirstIsis3ObjByType(root,coreObjType,&coreObj,&coreObjName,&coreObjParent)){
	    if (findFirstIsis3ObjByType(root,historyObjType,&historyObj,&historyObjName,&historyObjParent)){

			saveHistoryObjName = strdup(historyObjName);
			e = remove_struct_by_key(historyObjParent, historyObjName);
			if (e != NULL){
				mem_claim(e);
				add_struct(coreObjParent, saveHistoryObjName, e);
				rc = 1;
			}
			else {
				if (VERBOSE > 2){
					fprintf(stderr, "moveIsis3IsisHistoryToCore(): \"%s\" element could not be removed from \"%s\" object (%p)\n",
						saveHistoryObjName, historyObjType, e);
				}
				rc = 0;
			}
		}
		else {
			if (VERBOSE > 2){
				fprintf(stderr, "moveIsis3IsisHistoryToCore(): \"%s\" object not found\n", historyObjType);
			}
			rc = 0;
		}
	}
	else {
		if (VERBOSE > 2){
			fprintf(stderr, "moveIsis3IsisHistoryToCore(): \"%s\" object not found\n", coreObjType);
		}
		rc = 0;
	}

	return rc;
}

static int
undoReorgIsis3HistoryObj(Var *root){
	const char *funcName = "undoReorgIsis3HistoryObj()";
	const char *historyObjType = KW_OBJ_HISTORY;
	const char *dataObjName = "data";
	Var *e = NULL;
	Var *historyObj = NULL, *historyObjParent = NULL;
	char *historyObjName = NULL;
	Var *dataObj = NULL;
	char *eName = NULL;
	char *saveName = NULL;
	int rc = 1;
	int j, n = 0;
	int somethingRemoved = 0;
	int historyObjFound = 0;

	// find History by object type first
	if (findFirstIsis3ObjByType(root,historyObjType,&historyObj,&historyObjName,&historyObjParent)){
		historyObjFound = 1;
	}
	else {
		if (VERBOSE > 3)
			fprintf(stderr, "%s: \"%s\" object not found by %s\n", funcName, historyObjType, ISIS3_OBJ_TYPE_KEY);

		// if not found, try isis_struct_type next
		if (findFirstIsis3ObjByIsisStructType(root,IST_VAL_HISTORY,&historyObj,&historyObjName,&historyObjParent)){
			// if found, add missing History object type for later functions
			add_struct(historyObj, strdup(ISIS3_OBJ_TYPE_KEY), newString(strdup(historyObjType)));
			historyObjFound = 1;
		}
		else {
			if (VERBOSE > 3)
				fprintf(stderr, "%s: \"%s\" object not found by %s\n", funcName, historyObjType, ISIS3_STRUCT_TYPE_KEY);
			
			// TODO if not found, try by struct name
			//if (findFirstIsis3ObjByElementName(root,"history",&historyObj,&historyObjParent)){
			//}
		}
	}

	if (historyObjFound){
		// ensure StartByte and Bytes keywords exist
		if (find_struct(historyObj, KW_START_BYTE, NULL) < 0){
			add_struct(historyObj, strdup(KW_START_BYTE), newInt(0));
		}
		if (find_struct(historyObj, KW_BYTES, NULL) < 0){
			add_struct(historyObj, strdup(KW_BYTES), newInt(0));
		}
		// ensure Name keyword exists
		if (find_struct(historyObj, KW_NAME, NULL) < 0){
			add_struct(historyObj, strdup(KW_NAME), newString(strdup(KW_OBJ_ISISCUBE)));
		}

		find_struct(historyObj, dataObjName, &dataObj);
		if (dataObj == NULL){
			// create a sub-struct called "data"
			add_struct(historyObj, strdup(dataObjName), dataObj = new_struct(0));

			// move structs into "data" sub-struct
			n = get_struct_count(historyObj);
			j=0;
			while(j<n){
				somethingRemoved = 0;
				if (get_struct_element(historyObj, j, &eName, &e) > -1 && V_TYPE(e) == ID_STRUCT && strcmp(eName,dataObjName) != 0){
					if (VERBOSE > 3){
						fprintf(stderr, "%s: Moving \"%s\" struct (%p) from \"%s\" object (%p) to \"%s\" object (%p)\n",
							funcName, eName, e, historyObjType, historyObj, dataObjName, dataObj);
					}
					saveName = strdup(eName);
					e = remove_struct_by_key(historyObj, eName);
					if (e != NULL){
						mem_claim(e);
						add_struct(dataObj, saveName, e);
						somethingRemoved = 1;
					}
					else {
						if (VERBOSE > 3){
							fprintf(stderr, "%s: \"%s\" element could not be removed from \"%s\" object (%p)\n",
								funcName, saveName, historyObjName, historyObj);
						}
						rc=0;
					}
				}
				if (somethingRemoved){
					n--;
				}
				else {
					j++;
				}
			}
		}
		else {
			if (VERBOSE > 2){
				fprintf(stderr, "%s: object \"%s\" exists already in \"%s\" object (%p). Not reorganizing.\n",	
					funcName, dataObjName, historyObjName, historyObj);
			}
			rc=0;
		}
	}
	else {
		if (VERBOSE > 3){
			fprintf(stderr, "%s: \"%s\" object not found\n", funcName, historyObjType);
		}
		rc = 0;
	}

	return rc;
}


static Var *
do_loadISIS3(vfuncptr func, char *filename, int read_data, int use_names,
		int use_units, int include_tables, int include_original_label,
		int mimic_io_module) {

	char *fname = NULL;
	FILE *fp = NULL;
	int line_num = 0;
	Var **found_objs = NULL;
	char **found_names = NULL;
	Var **found_obj_parents = NULL;
	int n_found = 0;
	int i = 0;
	Var *e = NULL;

	Var *v = new_struct(0);

	if ((fname = dv_locate_file(filename)) == (char*) NULL) {
		parse_error("%s: Unable to expand filename %s\n", func->name, filename);
		return (NULL);
	}

	if (access(fname, R_OK) != 0) {
		parse_error("%s: Unable to find file %s (expanded to %s).", func->name, filename, fname);
		return (NULL);
	}

	/* is the file compressed */
	if ((fp = fopen(fname, "rb")) != NULL) {
		if (iom_is_compressed(fp)) {
			fclose(fp);
			fname = iom_uncompress_with_name(fname);
			fp = fopen(fname, "rb");
		}
	}

	if (isIsis3(fp)){
		// read label
		traverseIsis3Lbl(fname, fp, v, use_names, use_units, read_data, "root", &line_num, -1);

		// remove unwanted objects
		if (!include_tables){
			removeIsis3ObjsFromStruct(v,KW_OBJ_TABLE);
		}

		if (!include_original_label){
			removeIsis3ObjsFromStruct(v,KW_OBJ_ORGLBL);
		}

		// TODO read data separately from label

		if (mimic_io_module){
			// move IsisCub.Core.data to IsisCub.core
			moveIsis3CoreDataToTopLevel(v);

			// move Core.History.data.* to Core.History and delete Core.History.data
			reorgIsis3HistoryObj(v);

			// move IsisCub.History to IsisCub.Core.History
			moveIsis3HistoryToCore(v);

			// move IsisCub.OriginalLabel to IsisCub.Core.OriginalLabel
		}

		/*
		found_objs = NULL; found_names = NULL; found_obj_parents = NULL; n_found = 0;
		findIsis3ObjsByType(v,"Core",&found_objs,&found_names,&found_obj_parents,&n_found);
		fprintf(stderr, "Found %d Core objects.\n", n_found);
		found_objs = NULL; found_names = NULL; found_obj_parents = NULL; n_found = 0;
		findIsis3ObjsByType(v,"Table",&found_objs,&found_names,&found_obj_parents,&n_found);
		fprintf(stderr, "Found %d Table objects.\n", n_found);
		found_objs = NULL; found_names = NULL; found_obj_parents = NULL; n_found = 0;
		findIsis3ObjsByType(v,"History",&found_objs,&found_names,&found_obj_parents,&n_found);
		fprintf(stderr, "Found %d History objects.\n", n_found);
		found_objs = NULL; found_names = NULL; found_obj_parents = NULL; n_found = 0;
		findIsis3ObjsByType(v,"OriginalLabel",&found_objs,&found_names,&found_obj_parents,&n_found);
		fprintf(stderr, "Found %d OriginalLabel objects.\n", n_found);
		*/
	}
	else {
		parse_error("%s: File %s is not an ISIS3 file.", func->name, filename);
	}

	fclose(fp);

	if (filename != fname){
		free(fname);
	}

	return (v);
}

char get_keyword_datatype(char * value, char * name) {
	/* Determines the davinci datatype to apply to a value string, given its value
	 and its name for hints. */
	char * endptr;
	int intval;
	double floatval;
	int is_int = 0, is_double = 0;
	errno = 0;

	/* check for int value. Note that the whole string must convert to be an int
	 or it is more likely a string like a date/time value */

	intval = strtol(value, &endptr, 10);
	if (errno)
		is_int = 0;
	else
		is_int = 1;
	if (endptr != value + strlen(value))
		is_int = 0;

	/* check for float value. Note that like the int, the whole string must convert
	 to be a float or it is more likely a string like a date/time value */

	floatval = strtod(value, &endptr);
	if (errno)
		is_double = 0;
	else
		is_double = 1;
	if (endptr != value + strlen(value))
		is_double = 0;

	/* if both tests pass, check to see if they are numerically equal. Floating point
	 values only occasionally integral, and davinci can do the appropriate casting
	 in any case, so it's a good compromise. */

	/*  If the name of the field contains the string 'Version', don't translate it
	 to a number, but keep it as a string.
	 */

	if (name != NULL && strstr(name, "Version") != NULL) {
		is_int = 0;
		is_double = 0;
	}
	/* drd
	 * If the name contains the string 'SpacecraftClockCount', keep this as a string
	 */

	if (name != NULL && strstr(name, "SpacecraftClockCount") != NULL) {
		is_int = 0;
		is_double = 0;
	}

	/* drd
	 * If the value is an empty string of "", keep it a string
	 */

	if ((name != NULL) && (value[0] == '\"') && (value[1] == '\"')) {
		is_int = 0;
		is_double = 0;
		value[0] = '\0'; // The output routine will give us the desired "" for "Nothing"
	}

	if (name != NULL) {
		if (is_int && is_double) {
			if (intval == floatval) {
				is_double = 0;
				// drd added one more test -- if there is a decimal point, leave it a double
				if (strstr(value, ".") != NULL)
					is_double = 1;
			} else {
				is_int = 0;
			}
		}
	}

	if (is_double)
		return 'd';
	if (is_int)
		return 'i';
	return 'c';

}

int
isIsis3(FILE *fp){
	char buff[1024];
	char val[128];
	long pos = 0;

	memset(buff, 0, sizeof(buff));
	pos = ftell(fp);
	rewind(fp);
	fgets(buff, sizeof(buff)-1, fp);
	trim(buff,NULL);
	fseek(fp, pos, SEEK_SET); // move file pointer back
	sprintf(val, "Object = %s", KW_OBJ_ISISCUBE);
	return (strcmp(buff, val) == 0);
}

Var *
dv_LoadISIS3(FILE *fp, char *filename, struct iom_iheader *s)
{
	int line_num = 0;
	ssize_t file_size = 0;
	Var *root = NULL;
	Var *data_var = NULL;
	char *coreObjName = NULL;
	Var *coreObj = NULL, *coreObjParent = NULL;

	// TODO
	if (isIsis3(fp)){
		root = new_struct(0);
		traverseIsis3Lbl(filename, fp, root, 0, 0, 0, "root", &line_num, -1);

		if (findFirstIsis3ObjByType(root,KW_OBJ_CORE,&coreObj,&coreObjName,&coreObjParent)){
			data_var = readIsis3Core(coreObj, filename);
		}

		mem_claim(root);
		free_var(root);
	}

	return data_var;
}



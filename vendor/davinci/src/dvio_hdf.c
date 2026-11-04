#include "parser.h"
#include <sys/stat.h>
#include "endian_norm.h"

#ifdef HAVE_LIBHDF5


#define int_swap(a,b) \
{\
	int t;\
	t=(a); (a)=(b); (b)=t;\
}

#define HDF5_COMPRESSION_LEVEL 6

#include <hdf5.h>


#define ATTR_ORG "org"
#define ATTR_LINES "lines"
#define ATTR_STD "dv_std"

/** type of iter_data passed into dataset_attr_iter() */
typedef struct {
	int has_org_attr;
	int has_dv_std_attr;
	int org;
	int has_lines_attr;
	int lines;
} dv_h5_dataset_attr_iter_data;

/**
 * type of iter_data passed into group_iter()
 */
typedef struct {
	dv_h5_dim_handling dim_handling; /* input: size / dim handling */
	Var *data; /* output VAR */
} dv_h5_group_iter_data;


Var *load_hdf5(hid_t parent, dv_h5_dim_handling dim_handling);

void
WriteHDF5(hid_t parent, char *name, Var *v, int old_hdf)
{
    hid_t dataset, datatype, dataspace, aid2, attr, child, plist;
    hsize_t size[3];
    int org;
    int top = 0;
    int i;
    hsize_t length;
    Var *e;
    int lines,bsize,index;
    char * temp_data;
    unsigned char buf[256];

    if (V_NAME(v) != NULL) {
        if ((e = eval(v)) != NULL) v = e;
    }
    if (v == NULL || V_TYPE(v) == ID_UNK) {
        parse_error("Can't find variable");
        return;
    }
    

    if (parent < 0) {
        top = 1;
        parent = H5Fcreate(name, H5F_ACC_TRUNC, H5P_DEFAULT, H5P_DEFAULT);
    }

    switch (V_TYPE(v)) {
    case ID_STRUCT:

    {
        Var *d;
        char *n;
        /*
        ** member is a structure.  We need to create a sub-group
        ** with this name.
        */
        if (top == 0) {
            child = H5Gcreate(parent, name, 0);
        } else {
            child = parent;
        }
        for (i = 0 ; i < get_struct_count(v) ; i++) {
            get_struct_element(v, i, &n, &d);
            WriteHDF5(child, n, d, old_hdf);
        }
        if (top == 0) H5Gclose(child);
        break;
    }

    case ID_VAL:

        /*
        ** member is a value.  Create a dataset
        */
        for (i = 0 ; i < 3 ; i++) {
			if (old_hdf){
				size[i] = V_SIZE(v)[i];
			}
			else {
				size[2-i] = V_SIZE(v)[i];
			}
        }
        org = V_ORG(v);
        dataspace = H5Screate_simple(3, size, NULL);
        switch(V_FORMAT(v)) {
        case BYTE:  datatype = H5Tcopy(H5T_STD_U8BE); break;
        case SHORT: datatype = H5Tcopy(H5T_STD_I16BE); break;
        case USHORT: datatype = H5Tcopy(H5T_STD_U16BE); break; // drd Bug 2208 Loading a particular hdf5 file kills davinci
        case INT:   datatype = H5Tcopy(H5T_STD_I32BE); break;
        case LONG:   datatype = H5Tcopy(H5T_STD_I64BE); break;
        case FLOAT: datatype = H5Tcopy(H5T_IEEE_F32BE); break;
        case DOUBLE: datatype = H5Tcopy(H5T_IEEE_F64BE); break;
        }

	/*
	** Enable chunking and compression - JAS
	*/
	plist = H5Pcreate(H5P_DATASET_CREATE);
	H5Pset_chunk(plist, 3, size);
	H5Pset_deflate(plist, HDF5_COMPRESSION_LEVEL);

        dataset = H5Dcreate(parent, name, datatype, dataspace, plist);
#ifdef WORDS_BIGENDIAN
        H5Dwrite(dataset, datatype, 
                 H5S_ALL, H5S_ALL, H5P_DEFAULT, V_DATA(v));
#else
	temp_data = var_endian(v);
	if (temp_data != NULL) {
	  H5Dwrite(dataset, datatype,
		   H5S_ALL, H5S_ALL, H5P_DEFAULT, temp_data);
	  free(temp_data);
	}
#endif

        aid2 = H5Screate(H5S_SCALAR);
        attr = H5Acreate(dataset, ATTR_ORG, H5T_STD_I32BE, aid2, H5P_DEFAULT);
#ifndef WORDS_BIGENDIAN
        intswap(org);
#endif
        H5Awrite(attr, H5T_STD_U32BE, &org);
        H5Aclose(attr);
        if (!old_hdf) {
			int dv_std_value = 1;
            attr = H5Acreate(dataset, ATTR_STD, H5T_STD_I32BE, aid2, H5P_DEFAULT);
#ifndef WORDS_BIGENDIAN
	        intswap(dv_std_value);
#endif
            H5Awrite(attr, H5T_STD_U32BE, &dv_std_value);
            H5Aclose(attr);
        }
        H5Sclose(aid2);

        H5Tclose(datatype);
        H5Sclose(dataspace);
        H5Dclose(dataset);
	H5Pclose(plist);
        break;


    case ID_STRING:
        /*
        ** Member is a string of characters
        */

        lines=1;
        length=1;/*Set length to 1, and size to length*/
        dataspace = H5Screate_simple(1,&length,NULL);
        length=strlen(V_STRING(v))+1;/*String+NULL*/
        datatype = H5Tcopy(H5T_C_S1);
        H5Tset_size(datatype,length);
        dataset = H5Dcreate(parent,name, datatype, dataspace, H5P_DEFAULT);
        H5Dwrite(dataset, datatype,H5S_ALL, H5S_ALL, H5P_DEFAULT, V_STRING(v));

        aid2 = H5Screate(H5S_SCALAR);
        attr = H5Acreate(dataset, ATTR_LINES, H5T_STD_I32BE, aid2, H5P_DEFAULT);
#ifndef WORDS_BIGENDIAN
	intswap(lines);
#endif
        H5Awrite(attr, H5T_STD_I32BE, &lines);
        H5Sclose(aid2);
        H5Aclose(attr);


        H5Tclose(datatype);
        H5Sclose(dataspace);
        H5Dclose(dataset);

        break;

    case ID_TEXT:
    {
        unsigned char *big;
        int big_size=0;
        int stln=0;
        int i;

        /*Pack the array into a single buffer with newlines*/
        for (i=0;i<V_TEXT(v).Row;i++){
            big_size+=strlen(V_TEXT(v).text[i])+1;/* Added 1 for \n char */
        }
        big_size++; /*Final NULL*/
        big=(unsigned char *)calloc(big_size,sizeof(char));
        big_size=0;
        for (i=0;i<V_TEXT(v).Row;i++){
            stln=strlen(V_TEXT(v).text[i]);
            memcpy((big+big_size),V_TEXT(v).text[i],stln);
            big_size+=stln;
            big[big_size]='\n';
            big_size++;
        }
        big[big_size]='\0';
        big_size++;

        /*Now we can write out this big fat array*/
        length=1;
        dataspace = H5Screate_simple(1,&length,NULL);	
        datatype = H5Tcopy(H5T_C_S1);
        H5Tset_size(datatype,big_size);
        dataset = H5Dcreate(parent,name, datatype, dataspace, H5P_DEFAULT);
        H5Dwrite(dataset, datatype,H5S_ALL, H5S_ALL, H5P_DEFAULT, big);
        lines=V_TEXT(v).Row;
        aid2 = H5Screate(H5S_SCALAR);
        attr = H5Acreate(dataset, ATTR_LINES, H5T_STD_I32BE, aid2, H5P_DEFAULT);
#ifndef WORDS_BIGENDIAN
	intswap(lines);
#endif
        H5Awrite(attr, H5T_STD_I32BE, &lines);

        H5Sclose(aid2);
        H5Aclose(attr);
        H5Tclose(datatype);
        H5Sclose(dataspace);
        H5Dclose(dataset);
        free(big);
	
    }
	
    break;

    }

    if (top) H5Fclose(parent);
    return;
}

/**
 * Finds various dataset attr
 */
static herr_t
dataset_attr_iter(hid_t parent, const char *attr_name, void *iter_data)
{
    hid_t attr;
	dv_h5_dataset_attr_iter_data *data = (dv_h5_dataset_attr_iter_data *)iter_data;

	if (attr_name != NULL){
		if (strcasecmp(attr_name,ATTR_ORG) == 0){
			data->has_org_attr = 1;

            if ((attr = H5Aopen_name(parent, attr_name)) < 0){
				fprintf(stderr, "Unable to read attribute %s\n", attr_name);
			}
			else {
				H5Aread(attr, H5T_STD_I32BE, &data->org);
#ifndef WORDS_BIGENDIAN
				intswap(data->org);
#endif
				H5Aclose(attr);
			}
		}
		else if (strcasecmp(attr_name,ATTR_STD) == 0){
			data->has_dv_std_attr = 1;
		}
		else if (strcasecmp(attr_name,ATTR_LINES) == 0){
			data->has_lines_attr = 1;

            if ((attr = H5Aopen_name(parent, attr_name)) < 0){
				fprintf(stderr, "Unable to read attribute %s\n", attr_name);
			}
			else {
				H5Aread(attr, H5T_STD_I32BE, &data->lines);
#ifndef WORDS_BIGENDIAN
				intswap(data->lines);
#endif
				H5Aclose(attr);
			}
		}
	}

	return 1; // immediately return
}

#define FILL(array,val) { int _n=sizeof(array)/sizeof((array)[0]); int _i; for(_i=0; _i<_n; _i++){ (array)[_i]=(val); } }

/**
 * Make a VAR out of a HDF5 object
 * iter_data is of type dv_h5_group_iter_data
 */
static herr_t
group_iter(hid_t parent, const char *name, void *iter_data)
{
    H5G_stat_t buf;
    hid_t child, dataset, dataspace, datatype, attr;
    int type, size[3],  dsize, i;
    int var_type;
    hsize_t datasize[3], maxsize[3];
    int ndims = 0;
    H5T_class_t classtype;
    Var *v = NULL;
    void *databuf, *databuf2;
    int Lines=1;
	extern int VERBOSE;
	dv_h5_dataset_attr_iter_data attr_info;
	int nattr, j, k;
	int old_hdf;

    FILL(size,1);
    FILL(datasize,1);
    FILL(maxsize,1);

    ((dv_h5_group_iter_data *)iter_data)->data = NULL;

    if (H5Gget_objinfo(parent, name, 1, &buf) < 0) return -1;
    type = buf.type;


    switch (type)  {
    case H5G_GROUP:
        child = H5Gopen(parent, name);
        v = load_hdf5(child, ((dv_h5_group_iter_data *)iter_data)->dim_handling);
		if (v != NULL){
			V_NAME(v) = (name ? strdup(name) : 0);
		}
		else {
			parse_error("Unable to load sub-structure \"%s\", skipping!\n", name);
		}
        H5Gclose(child);
        break;

    case H5G_DATASET:
        if ((dataset = H5Dopen(parent, name)) < 0) {
            return -1;
        }

        datatype = H5Dget_type(dataset);
        classtype=(H5Tget_class(datatype));

        if (classtype==H5T_INTEGER){
            if (H5Tequal(datatype , H5T_STD_U8BE) || H5Tequal(datatype, H5T_STD_U8LE) || H5Tequal(datatype, H5T_NATIVE_UCHAR)) 
                type = BYTE;
            else if (H5Tequal(datatype , H5T_STD_I16BE) || H5Tequal(datatype , H5T_STD_I16LE) || H5Tequal(datatype, H5T_NATIVE_SHORT))
                type = SHORT;
            else if (H5Tequal(datatype , H5T_STD_U16BE) || H5Tequal(datatype , H5T_STD_U16LE)) // drd Bug 2208 Loading a particular hdf5 file kills davinci
                type = USHORT;
            else if (H5Tequal(datatype , H5T_STD_I32BE) || H5Tequal(datatype , H5T_STD_I32LE) || H5Tequal(datatype, H5T_NATIVE_INT))   
                type = INT;
            else if (H5Tequal(datatype , H5T_STD_U32BE) || H5Tequal(datatype , H5T_STD_U32LE))
                type = UINT;
            else if (H5Tequal(datatype , H5T_STD_I64BE) || H5Tequal(datatype , H5T_STD_I64LE) || H5Tequal(datatype, H5T_NATIVE_LLONG))   
                type = LONG;
        }
        else if (classtype==H5T_FLOAT){
            if (H5Tequal(datatype , H5T_IEEE_F32BE) || H5Tequal(datatype , H5T_IEEE_F32LE) || H5Tequal(datatype, H5T_NATIVE_FLOAT)) 
                type = FLOAT;
            else if (H5Tequal(datatype , H5T_IEEE_F64BE) || H5Tequal(datatype , H5T_IEEE_F64LE) || H5Tequal(datatype, H5T_NATIVE_DOUBLE)) 
                type = DOUBLE;
        }

        else if (classtype==H5T_STRING){
            type=ID_STRING;
        }


        if (type!=ID_STRING){
			memset(&attr_info,0,sizeof(attr_info));
			attr_info.org = BSQ;

			nattr = H5Aget_num_attrs(dataset);
			k = 0;
			for(j=0; j<nattr; j++){
				H5Aiterate(dataset, &k, dataset_attr_iter, &attr_info);
			}

			if (!attr_info.has_org_attr){
				parse_error("Unable to get org for \"%s\". Assuming %s.\n", name, Org2Str(attr_info.org));
			}
        }
        else {
			memset(&attr_info,0,sizeof(attr_info));
			nattr = H5Aget_num_attrs(dataset);
			k = 0;
			for(j=0; j<nattr; j++){
				H5Aiterate(dataset, &k, dataset_attr_iter, &attr_info);
			}

			if (!attr_info.has_lines_attr){
				Lines = 0;
                parse_error("Unable to get \"%s\" for \"%s\". Assuming %d unless we can find otherwise.\n", ATTR_LINES, name, Lines);
			}
			else {
				Lines = attr_info.lines;
			}
        }

		dataspace = H5Dget_space(dataset);
		ndims = H5Sget_simple_extent_ndims(dataspace);
		// bail if ndims > 3
		if (ndims > 3){
			parse_error("Dataset \"%s\" has %d dimensions, which is more than we can handle. Skipping.\n", name, ndims);
			return 1; // return value passed to H5Giterate(), see elsewhere in this file
		}

		H5Sget_simple_extent_dims(dataspace, datasize, maxsize);
		for (i = 0 ; i < ndims ; i++) {
			size[ndims-1-i] = datasize[ndims-1-i];
		}

        if ((type!=ID_STRING)){
            dsize = H5Sget_simple_extent_npoints(dataspace);
            databuf = calloc(dsize, NBYTES(type));
            H5Dread(dataset, datatype, H5S_ALL, H5S_ALL, H5P_DEFAULT, databuf);
#ifdef WORDS_BIGENDIAN
            if (H5Tget_order(datatype) == H5T_ORDER_LE){
                databuf2 = flip_endian(databuf, dsize, NBYTES(type));
                free(databuf);
                databuf = databuf2;
            }
#else
            if (H5Tget_order(datatype) == H5T_ORDER_BE){
                databuf2 = flip_endian(databuf, dsize, NBYTES(type));
                free(databuf);
                databuf = databuf2;
            }
#endif /* WORDS_BIGENDIAN */
            H5Tclose(datatype);
            H5Sclose(dataspace);
            H5Dclose(dataset);
	    
            /*
             * // drd Bug 2208 Loading a particular hdf5 file kills davinci
             * For the time being, there is no USHORT type
             * functionally available in davinci.
             * We can promote any USHORT value to INT
             * and not change sign
             */
            if(type == USHORT) { // promote to INT
            	int i;
				databuf = (char *)realloc(databuf, dsize*NBYTES(INT));
            	for(i = dsize-1; i >= 0; i--) {
            		((int*)databuf)[i] = (int)((unsigned short *)databuf)[i];
            	}
            	type = INT;
            }
			else if (type == UINT) {
            	int i;
				databuf = (char *)realloc(databuf, dsize*NBYTES(LONG));
            	for(i = dsize-1; i >= 0; i--) {
            		((long*)databuf)[i] = ((unsigned int *)databuf)[i];
            	}
            	type = LONG;
			}
			else if (type == LONG) {
            	int i;
				databuf = (char *)realloc(databuf, dsize*NBYTES(LONG));
            	for(i = dsize-1; i >= 0; i--) {
            		((long*)databuf)[i] = (long)((long *)databuf)[i];
            	}
            	type = LONG;
			}

			if (((dv_h5_group_iter_data *)iter_data)->dim_handling == DV_H5_DIM_OLD_HANDLING){
				/* user forced old size / dim handling */
				old_hdf = 1;
			}
			else if (((dv_h5_group_iter_data *)iter_data)->dim_handling == DV_H5_DIM_NEW_HANDLING){
				/* user forced new size / dim handling */
				old_hdf = 0;
			}
			else {
				/* no forced size / dim handling: determine from dv_std and org attributes */
				if (attr_info.has_org_attr){
					/* a davinci file: its an old hdf if no dv_std attr is not present */
					old_hdf = attr_info.has_dv_std_attr? 0: 1;
				}
				else {
					/* not a davinci file - assume standard reading method */
					old_hdf = 0;
				}
			}
            if (!old_hdf) {
                /* flip dimensions; HDF dimenions have the fastest changing element last */
                for(i=0;i<(ndims/2);i++){
                    int_swap(size[ndims-1-i],size[i]);
                }
            }

            v = newVal(attr_info.org, size[0], size[1], size[2], type, databuf);

            V_NAME(v) = strdup(name);
        }	

        else {
			// bail if ndims > 1
			if (ndims > 1){
				parse_error("Dataset \"%s\" has %d dimensions, which is more than we can handle. Skipping.\n", name, ndims);
				return 1; // return value passed to H5Giterate(), see elsewhere in this file
			}

/*       	dsize = H5Sget_simple_extent_npoints(dataspace);*/
            dsize = H5Tget_size(datatype);

            v=newVar();
			if (attr_info.has_lines_attr){
				// standard davinci file -- Lines attribute exists in the file
				// lines are organized as a single string with newline as separator
				
				databuf = (unsigned char *)calloc(dsize*(size[0]+1), sizeof(char));
				H5Dread(dataset, datatype, H5S_ALL, H5S_ALL, H5P_DEFAULT, databuf);

				if (Lines==1 && ((char *)databuf)[strlen((char *)databuf)-1] != '\n') {
					V_TYPE(v)=ID_STRING;
					V_STRING(v)=databuf;
				}
				else { /*Now we have to dissable to the large block of text*/
					int lm=0,nm=0;
					int len=strlen(databuf);
					int index=0;

					V_TYPE(v)=ID_TEXT;
					V_TEXT(v).Row=Lines;
					V_TEXT(v).text=(char **)calloc(Lines+1,sizeof(char *)); // Lines+1 to handle Lines=0

					/*send nm through databuf looking for \n.*/
					while (nm < len) {
						if (((char *)databuf)[nm]=='\n'){
							V_TEXT(v).text[index]=malloc(nm-lm+1);
							memcpy(
								V_TEXT(v).text[index],
								(char *)databuf+lm,
								(nm-lm+1));
							V_TEXT(v).text[index][nm-lm]='\0';
							index++;
							nm++;/*Next line or end*/
							lm=nm;
						}
						else if (nm == (len-1)) {
							/*
							 * drd Bug 2208 Loading a particular hdf5 file kills davinci
							 * This is the case where we are at the end of a 'string' data set,
							 * but the end is not a newline
							 *
							 */
							V_TEXT(v).text[index]=malloc(nm-lm+2);
							memcpy(
								V_TEXT(v).text[index],
								(char *)databuf+lm,
								(nm-lm+2));
							V_TEXT(v).text[index][nm-lm+1]='\0';
							nm++; // This increment will break out of while() loop
						}

						else 	
							nm++;
					}
				}
			}
			else {
				// non-standard davinci file -- Lines attribute does not exist in the file
				// if we did not find Lines - assume it is equal to size[0]
				Lines = size[0];
                parse_error("Unable to get lines for \"%s\" (non-davinci HDF5 text dataset). Assuming %d.\n", name, Lines);
                V_TYPE(v)=ID_TEXT;
                V_TEXT(v).Row=Lines;
                V_TEXT(v).text=(char **)calloc(Lines+1,sizeof(char *)); // Lines+1 to handle Lines=0
				for(i=0;i<Lines;i++){
					(V_TEXT(v).text)[i] = calloc(dsize+1,sizeof(char *));
				}
				H5Dread(dataset, datatype, H5S_ALL, H5S_ALL, H5P_DEFAULT, V_TEXT(v).text);
			}
			
            H5Sclose(dataspace);
            H5Dclose(dataset);
            V_NAME(v) = strdup(name);
        }
    }
	if (VERBOSE > 2) {
		pp_print_var(v, V_NAME(v), 0, 0);
	}

    ((dv_h5_group_iter_data *)iter_data)->data = v;
    return 1;
}


static herr_t
count_group(hid_t group, const char *name, void *data)
{
    *((int *)data) += 1;
    return(0);
}

Var *
LoadHDF5(char *filename, dv_h5_dim_handling dim_handling)
{
    Var *v;
    hid_t group;
    hid_t file;

    if (H5Fis_hdf5(filename) == 0) {
        return(NULL);
    } 

    file = H5Fopen(filename, H5F_ACC_RDONLY, H5P_DEFAULT);

    if (file < 0) return(NULL);

    group = H5Gopen(file, "/");

    v = load_hdf5(group, dim_handling);

    H5Gclose(group);
    H5Fclose(file);
    return(v);
}


Var *
load_hdf5(hid_t parent, dv_h5_dim_handling dim_handling)
{
    Var *o, *e = NULL;
    int count = 0;
    int idx = 0;
    herr_t ret;
	dv_h5_group_iter_data iter_data = {dim_handling, NULL};

    H5Giterate(parent, ".", NULL, count_group, &count);

    if (count < 0) {
        parse_error("Group count < 0");
        return(NULL);
    }
    
    o = new_struct(count);
    
    while ((ret = H5Giterate(parent, ".", &idx, group_iter, &iter_data)) > 0)  {
		if (iter_data.data != NULL) {
			add_struct(o, V_NAME(iter_data.data), iter_data.data);
			V_NAME(iter_data.data) = NULL;
		}
		if (idx == count) break;
    }
    return(o);
}

#endif

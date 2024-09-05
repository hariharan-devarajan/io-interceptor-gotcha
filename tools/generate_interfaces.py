import argparse
import clang.cindex as cix
import os
import shutil
from datetime import datetime
from string import Template

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Generate interfaces script")
parser.add_argument("--libclang-path", type=str, help="Path to libclang", required=True)
parser.add_argument(
    "--hdf5-header-path",
    type=str,
    help="Path to HDF5 library header file",
    required=True,
)
parser.add_argument(
    "--verbose", action="store_true", help="Print verbose output", default=False
)
cli_args = parser.parse_args()

cix.Config.set_library_file(cli_args.libclang_path)


def print_function(cursor):
    if not cli_args.verbose:
        return
    print("-" * 80)
    print(f"[func] {cursor.spelling}")
    for i, arg in enumerate(cursor.get_arguments()):
        args = []
        args.append(f"[arg{i}]")
        args.append(f"s: {arg.spelling}")
        args.append(f"tk: {arg.type.kind}")
        args.append(f"ts: {arg.type.spelling}")
        if arg.type.kind == cix.TypeKind.INCOMPLETEARRAY:
            args.append(f"tek: {arg.type.element_type.kind}")
            args.append(f"tes: {arg.type.element_type.spelling}")
        elif arg.type.kind == cix.TypeKind.CONSTANTARRAY:
            args.append(f"tek: {arg.type.element_type.kind}")
            args.append(f"tes: {arg.type.element_type.spelling}")
            args.append(f"tc: {arg.type.element_count}")
        print(" ".join(args))
    print("-" * 80)


TEMPLATE_IMPLEMENTATION = Template("""
///
/// This file is generated by tools/generate_interfaces.py
/// Generated on: ${timestamp}
///

#include <brahma/interface/${name}.h>
#include <stdexcept>

#ifdef BRAHMA_ENABLE_${namespace}

${macros}
                                   
int update_${name}(gotcha_binding_t *&bindings, size_t &binding_index) {
    ${macro_bindings}
    return 0;
}
                                   
size_t count_${name}() {
    return ${count};
}
                                   
namespace brahma {
    std::shared_ptr<${namespace}> ${namespace}::my_instance = nullptr;
                                   
    std::shared_ptr<${namespace}> ${namespace}::get_instance() {
        if (my_instance == nullptr) {
            BRAHMA_LOG_INFO("${namespace} class not intercepted but used", "");
            my_instance = std::make_shared<${namespace}>();
        }
        return my_instance;
    }
                                   
    int ${namespace}::set_instance(std::shared_ptr<${namespace}> instance_i) {
        if (instance_i != nullptr) {
            my_instance = instance_i;
            return 0;
        } else {
            BRAHMA_LOG_ERROR("%s instance_i is not set", "${namespace}");
            throw std::runtime_error("instance_i is not set");
        }
    }
 
    ${wrapper_functions}
}

#endif // BRAHMA_ENABLE_${namespace}
""")

TEMPLATE_INTERFACE = Template("""
///
/// This file is generated by tools/generate_interfaces.py
/// Generated on: ${timestamp}
///

#ifndef BRAHMA_${namespace}_H
#define BRAHMA_${namespace}_H
#include <brahma/brahma_config.hpp>
#ifdef BRAHMA_ENABLE_${namespace}
#include <brahma/interceptor.h>
#include <brahma/interface/interface.h>
#include <stdexcept>
#include <${header_file}>

namespace brahma {
    class ${namespace} : public Interface {
        private:
            static std::shared_ptr<${namespace}> my_instance;
                             
        public:
            ${namespace}() : Interface() {};
            
            virtual ~${namespace}() {};

            static std::shared_ptr<${namespace}> get_instance();
                             
            static int set_instance(std::shared_ptr<${namespace}> instance_i);
                              
            ${virtual_functions}
    };
}

${macro_typedefs}

#endif // BRAHMA_ENABLE_${namespace}
#endif // BRAHMA_${namespace}_H
        """)

TEMPLATE_MACRO = Template("""
    GOTCHA_MACRO(${function_name}, ${return_type}, (${args}), (${arg_names}), brahma::${namespace});
""")

TEMPLATE_MACRO_BINDING = Template("""
    GOTCHA_BINDING_MACRO(${function_name});
""")

TEMPLATE_MACRO_TYPEDEF = Template("""
    GOTCHA_MACRO_TYPEDEF(${function_name}, ${return_type}, (${args}), (${arg_names}), brahma::${namespace});
""")

TEMPLATE_VIRTUAL_FUNCTION = Template("""
    virtual ${return_type} ${function_name}(${args});
""")

TEMPLATE_WRAPPER_FUNCTION = Template("""
    ${return_type} ${namespace}::${function_name}(${args}) {
        BRAHMA_UNWRAPPED_FUNC(${function_name}, ${return_type}, (${arg_names}));
        return result;
    }
""")


index = cix.Index.create()

# Interface generation rules (name, header file, header file path, prefix)
interfaces = [
    ("hdf5", "hdf5.h", cli_args.hdf5_header_path, "H5"),
]

# Define interface and implementation file paths
script_dir = os.path.dirname(os.path.abspath(__file__))
implementation_dir = os.path.join(script_dir, "../src/brahma/interface")
interface_dir = os.path.join(script_dir, "../include/brahma/interface")

# Generate timestamp
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Generate interfaces
for name, header_file, header_file_path, prefix in interfaces:
    print(f"[{name}] Generating interface...")

    translation_unit = index.parse(header_file_path)

    implementation_path = f"{implementation_dir}/{name}.cpp"
    interface_path = f"{interface_dir}/{name}.h"
    namespace = name.upper()

    macros = []
    macro_bindings = []
    macro_typedefs = []
    virtual_functions = []
    wrapper_functions = []

    for cursor in translation_unit.cursor.get_children():
        if cursor.kind == cix.CursorKind.FUNCTION_DECL:
            if prefix not in cursor.spelling:
                continue

            print_function(cursor)

            args = []
            arg_names = []
            for arg in cursor.get_arguments():
                if arg.type.kind == cix.TypeKind.INCOMPLETEARRAY:
                    args.append(f"{arg.type.element_type.spelling} {arg.spelling}[]")
                elif arg.type.kind == cix.TypeKind.CONSTANTARRAY:
                    args.append(
                        f"{arg.type.element_type.spelling} {arg.spelling}[{arg.type.element_count}]"
                    )
                else:
                    args.append(f"{arg.type.spelling} {arg.spelling}")
                arg_names.append(arg.spelling)

            macros.append(
                TEMPLATE_MACRO.substitute(
                    {
                        "function_name": cursor.spelling,
                        "return_type": cursor.result_type.spelling,
                        "args": ", ".join(args),
                        "arg_names": ", ".join(arg_names),
                        "namespace": namespace,
                    }
                )
            )

            macro_bindings.append(
                TEMPLATE_MACRO_BINDING.substitute(
                    {
                        "function_name": cursor.spelling,
                    }
                )
            )

            macro_typedefs.append(
                TEMPLATE_MACRO_TYPEDEF.substitute(
                    {
                        "function_name": cursor.spelling,
                        "return_type": cursor.result_type.spelling,
                        "args": ", ".join(args),
                        "arg_names": ", ".join(arg_names),
                        "namespace": namespace,
                    }
                )
            )

            virtual_functions.append(
                TEMPLATE_VIRTUAL_FUNCTION.substitute(
                    {
                        "return_type": cursor.result_type.spelling,
                        "function_name": cursor.spelling,
                        "args": ", ".join(args),
                    }
                )
            )

            wrapper_functions.append(
                TEMPLATE_WRAPPER_FUNCTION.substitute(
                    {
                        "function_name": cursor.spelling,
                        "return_type": cursor.result_type.spelling,
                        "args": ", ".join(args),
                        "arg_names": ", ".join(arg_names),
                        "namespace": namespace,
                    }
                )
            )

    with open(interface_path, "w+") as interface_file:
        interface_file.write(
            TEMPLATE_INTERFACE.substitute(
                {
                    "header_file": header_file,
                    "namespace": namespace,
                    "macro_typedefs": "".join(macro_typedefs),
                    "virtual_functions": "".join(virtual_functions),
                    "timestamp": timestamp,
                }
            )
        )

    with open(implementation_path, "w+") as implementation_file:
        implementation_file.write(
            TEMPLATE_IMPLEMENTATION.substitute(
                {
                    "name": name,
                    "namespace": namespace,
                    "macros": "".join(macros),
                    "macro_bindings": "".join(macro_bindings),
                    "count": len(macros),
                    "wrapper_functions": "".join(wrapper_functions),
                    "timestamp": timestamp,
                }
            )
        )

    print(f"[{name}] Generated {len(macros)} functions")

    if shutil.which("clang-format") is None:
        print(f"[{name}] clang-format not found, skipping formatting")
    else:
        print(f"[{name}] Formatting files using clang-format...")
        os.system(f"clang-format -i {interface_path}")
        os.system(f"clang-format -i {implementation_path}")

    print(f"[{name}] Done!")
